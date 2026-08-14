#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from nas_control.config import Config
from nas_control.database import Database
from nas_control.service import NASService
from nas_control.truenas import get_api_key


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = Path(os.environ.get("WOL_NAS_DATA_DIR", ROOT / "data")).expanduser().resolve()
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "nas-control.sqlite3"
CSRF_TOKEN = secrets.token_urlsafe(32)


class NASHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], service: NASService, config: Config):
        super().__init__(address, handler)
        self.service = service
        self.config = config


class Handler(BaseHTTPRequestHandler):
    server: NASHTTPServer
    server_version = "NASControl/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        if path == "/":
            self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send_file(STATIC / "app.js", "text/javascript; charset=utf-8")
        elif path == "/styles.css":
            self._send_file(STATIC / "styles.css", "text/css; charset=utf-8")
        elif path == "/api/bootstrap":
            self._json(
                {
                    "csrf": CSRF_TOKEN,
                    "status": self.server.service.get_status(),
                    "activity": self.server.service.get_activity(),
                    "metrics": self.server.service.get_metrics("24h"),
                    "schedules": self.server.service.database.list_schedules(),
                    "history": self.server.service.database.list_history(100),
                    "settings": self.server.config.public_dict(bool(get_api_key(self.server.config))),
                }
            )
        elif path == "/api/status":
            self._json(self.server.service.get_status())
        elif path == "/api/activity":
            self._json(self.server.service.get_activity())
        elif path == "/api/metrics":
            params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
            try:
                self._json(self.server.service.get_metrics(params.get("range", "24h")))
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
        elif path == "/api/schedules":
            self._json(self.server.service.database.list_schedules())
        elif path == "/api/history":
            self._json(self.server.service.database.list_history(100))
        elif path == "/healthz":
            self._json({"ok": True})
        else:
            self._error(HTTPStatus.NOT_FOUND, "페이지를 찾을 수 없습니다.")

    def do_POST(self) -> None:
        if not self._check_csrf():
            return
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path in {"/api/actions/wake", "/api/actions/shutdown"}:
                action = path.rsplit("/", 1)[-1]
                if action == "shutdown" and payload.get("confirm") != "shutdown":
                    self._error(HTTPStatus.BAD_REQUEST, "종료 확인이 필요합니다.")
                    return
                history_id = self.server.service.trigger(action)
                self._json({"accepted": True, "history_id": history_id}, HTTPStatus.ACCEPTED)
            elif path == "/api/schedules":
                item = self.server.service.database.create_schedule(payload)
                self._json(item, HTTPStatus.CREATED)
            elif path.startswith("/api/schedules/"):
                schedule_id = int(path.rsplit("/", 1)[-1])
                item = self.server.service.database.update_schedule(schedule_id, payload)
                self._json(item)
            elif path == "/api/status/refresh":
                self._json(self.server.service.refresh_status())
            elif path == "/api/activity/refresh":
                self._json(self.server.service.refresh_activity())
            else:
                self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
        except (ValueError, KeyError) as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        except RuntimeError as error:
            self._error(HTTPStatus.CONFLICT, str(error))
        except Exception:
            logging.exception("Request failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "요청 처리 중 오류가 발생했습니다.")

    def do_DELETE(self) -> None:
        if not self._check_csrf():
            return
        path = urlparse(self.path).path
        if not path.startswith("/api/schedules/"):
            self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
            return
        try:
            schedule_id = int(path.rsplit("/", 1)[-1])
            self.server.service.database.delete_schedule(schedule_id)
            self._json({"deleted": True})
        except (ValueError, KeyError) as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))

    def _check_csrf(self) -> bool:
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), CSRF_TOKEN):
            self._error(HTTPStatus.FORBIDDEN, "보안 토큰이 올바르지 않습니다. 페이지를 새로고침하세요.")
            return False
        origin = self.headers.get("Origin")
        if origin:
            origin_host = urlparse(origin).netloc
            request_host = self.headers.get("Host", "")
            if origin_host != request_host:
                self._error(HTTPStatus.FORBIDDEN, "다른 사이트에서 보낸 요청은 허용되지 않습니다.")
                return False
        return True

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("요청이 너무 큽니다.")
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("JSON 요청 형식이 올바르지 않습니다.") from error
        if not isinstance(data, dict):
            raise ValueError("JSON 객체가 필요합니다.")
        return data

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "파일을 찾을 수 없습니다.")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")

    def log_message(self, format_string: str, *args: object) -> None:
        logging.info("%s - %s", self.client_address[0], format_string % args)


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / "nas-control.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler(sys.stdout)])


def main() -> None:
    parser = argparse.ArgumentParser(description="TrueNAS 전원 및 예약 웹 서비스")
    parser.add_argument("--check-config", action="store_true", help="설정을 검증하고 종료")
    args = parser.parse_args()
    config = Config.load(CONFIG_PATH)
    if not CONFIG_PATH.exists():
        config.save(CONFIG_PATH)
    if args.check_config:
        print(f"설정 정상: {CONFIG_PATH}")
        return
    setup_logging()
    database = Database(DB_PATH, config.timezone)
    service = NASService(config, database)
    server = NASHTTPServer((config.listen_host, config.listen_port), Handler, service, config)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    signal.signal(signal.SIGINT, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    service.start()
    logging.info("NAS Control listening on http://%s:%s", config.listen_host, config.listen_port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        service.stop()
        server.server_close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config
from .database import Database
from .network import check_status, http_ready, ping, send_magic_packet, tcp_open, wait_until
from .truenas import fetch_activity, get_api_key, request_shutdown


class NASService:
    def __init__(self, config: Config, database: Database) -> None:
        self.config = config
        self.database = database
        self.timezone = ZoneInfo(config.timezone)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nas-action")
        self.stop_event = threading.Event()
        self.action_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.activity_lock = threading.Lock()
        self._status: dict[str, Any] = {
            "online": False,
            "ready": False,
            "checks": {"ping": False, "web_ui": False, "smb": False, "nextcloud": False},
            "checked_at": None,
            "action": None,
        }
        self._activity: dict[str, Any] = {
            "available": False,
            "checked_at": None,
            "jobs": [],
            "pools": [],
            "active_scans": [],
            "iscsi_sessions": [],
            "smb_connections": [],
            "time_machine_backups": [],
            "resources": {"cpu_percent": 0, "memory": {}, "temperatures": {"disks": {}}},
            "io": {"disk_read_bps": 0, "disk_write_bps": 0, "network_rx_bps": 0, "network_tx_bps": 0},
            "summary": {"active_jobs": 0, "active_scans": 0, "iscsi_sessions": 0, "smb_sessions": 0, "smb_open_files": 0, "time_machine_backups": 0},
        }
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, name="nas-scheduler", daemon=True)
        self.status_thread = threading.Thread(target=self._status_loop, name="nas-status", daemon=True)

    def start(self) -> None:
        status = self.refresh_status()
        if status["online"]:
            self.refresh_activity()
        self.scheduler_thread.start()
        self.status_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def get_status(self) -> dict[str, Any]:
        with self.status_lock:
            result = dict(self._status)
            result["checks"] = dict(self._status["checks"])
        result["api_key_configured"] = bool(get_api_key(self.config))
        return result

    def refresh_status(self) -> dict[str, Any]:
        current = check_status(self.config)
        with self.status_lock:
            action = self._status.get("action")
            self._status.update(current)
            self._status["action"] = action
        return current

    def get_activity(self) -> dict[str, Any]:
        with self.activity_lock:
            return {
                **self._activity,
                "jobs": list(self._activity["jobs"]),
                "pools": list(self._activity["pools"]),
                "active_scans": list(self._activity["active_scans"]),
                "iscsi_sessions": list(self._activity["iscsi_sessions"]),
                "smb_connections": list(self._activity.get("smb_connections", [])),
                "time_machine_backups": list(self._activity.get("time_machine_backups", [])),
                "resources": {
                    **self._activity.get("resources", {}),
                    "memory": dict(self._activity.get("resources", {}).get("memory", {})),
                    "temperatures": {
                        **self._activity.get("resources", {}).get("temperatures", {}),
                        "disks": dict(self._activity.get("resources", {}).get("temperatures", {}).get("disks", {})),
                    },
                },
                "io": dict(self._activity["io"]),
                "summary": dict(self._activity["summary"]),
            }

    def refresh_activity(self) -> dict[str, Any]:
        try:
            activity = fetch_activity(self.config)
        except Exception as error:
            logging.warning("Activity refresh failed: %s", error)
            activity = self.get_activity()
            activity.update({"available": False, "error": "현재 활동 정보를 불러오지 못했습니다."})
        else:
            activity.pop("error", None)
            self.database.record_metrics(activity)
        with self.activity_lock:
            self._activity = activity
        return self.get_activity()

    def get_metrics(self, range_name: str = "24h") -> dict[str, Any]:
        return self.database.metrics_history(range_name)

    def trigger(self, action: str, source: str = "manual") -> int:
        if action not in {"wake", "shutdown"}:
            raise ValueError("알 수 없는 전원 동작입니다.")
        if not self.action_lock.acquire(blocking=False):
            raise RuntimeError("다른 전원 작업이 진행 중입니다.")
        try:
            history_id = self.database.begin_history(source, action)
            self.executor.submit(self._run_action, history_id, action, source)
            return history_id
        except Exception:
            self.action_lock.release()
            raise

    def _run_action(self, history_id: int, action: str, source: str) -> None:
        started = time.monotonic()
        status = "success"
        detail = ""
        self._set_action({"type": action, "source": source, "phase": "starting", "started_at": time.time()})
        try:
            try:
                if action == "wake":
                    detail = self._wake()
                else:
                    detail = self._shutdown()
            except Exception as error:
                logging.exception("NAS action failed")
                status = "failed"
                detail = str(error)
        finally:
            try:
                duration = time.monotonic() - started
                self.database.finish_history(history_id, status, detail, duration)
            finally:
                self._set_action(None)
                try:
                    self.refresh_status()
                finally:
                    self.action_lock.release()

    def _wake(self) -> str:
        current = self.refresh_status()
        if current["online"]:
            return "이미 NAS가 온라인이므로 WOL 전송을 건너뛰었습니다."
        self._update_phase("wol", "Magic Packet 전송 중")
        packets = send_magic_packet(self.config)
        retry_sent = False
        wake_started = time.monotonic()

        def on_ping_tick(_: float) -> None:
            nonlocal retry_sent, packets
            elapsed = time.monotonic() - wake_started
            self._update_phase("ping", f"네트워크 응답 대기 · {int(elapsed)}초")
            if not retry_sent and elapsed >= self.config.wol_retry_after:
                packets += send_magic_packet(self.config)
                retry_sent = True

        if not wait_until(lambda: ping(self.config.nas_ip), self.config.ping_timeout, self.config.check_interval, on_ping_tick):
            raise TimeoutError("부팅 제한 시간 내에 NAS의 네트워크 응답을 확인하지 못했습니다.")
        self._update_phase("services", "TrueNAS Web UI와 SMB 준비 대기")
        if not wait_until(
            lambda: tcp_open(self.config.nas_ip, self.config.web_ui_port) and tcp_open(self.config.nas_ip, self.config.smb_port),
            self.config.service_timeout,
            self.config.check_interval,
        ):
            raise TimeoutError("TrueNAS Web UI 또는 SMB가 제한 시간 내에 준비되지 않았습니다.")
        if self.config.nextcloud_port:
            self._update_phase("optional_http", "추가 HTTP 서비스 준비 대기")
            if not wait_until(
                lambda: http_ready(self.config.nas_ip, self.config.nextcloud_port),
                self.config.nextcloud_timeout,
                self.config.check_interval,
            ):
                raise TimeoutError("추가 HTTP 서비스가 제한 시간 내에 준비되지 않았습니다.")
        return f"NAS와 모든 서비스가 준비되었습니다. Magic Packet {packets}회 전송."

    def _shutdown(self) -> str:
        current = self.refresh_status()
        if not current["online"]:
            return "이미 NAS가 오프라인이므로 종료 요청을 건너뛰었습니다."
        self._update_phase("request", "TrueNAS 정상 종료 요청 중")
        request_shutdown(self.config)
        self._update_phase("offline", "NAS 종료 확인 중")
        if not wait_until(lambda: not ping(self.config.nas_ip), 180, self.config.check_interval):
            raise TimeoutError("종료 요청 후 3분 내에 NAS 오프라인 상태를 확인하지 못했습니다.")
        return "TrueNAS 정상 종료를 확인했습니다."

    def _set_action(self, action: dict[str, Any] | None) -> None:
        with self.status_lock:
            self._status["action"] = action

    def _update_phase(self, phase: str, message: str) -> None:
        with self.status_lock:
            if self._status["action"]:
                self._status["action"].update({"phase": phase, "message": message})

    def _scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                now = datetime.now(self.timezone).replace(second=0, microsecond=0)
                for schedule in self.database.due_schedules(now):
                    try:
                        self.trigger(schedule["action"], f"schedule:{schedule['id']}")
                    except RuntimeError:
                        history_id = self.database.begin_history(f"schedule:{schedule['id']}", schedule["action"])
                        self.database.finish_history(history_id, "skipped", "다른 전원 작업이 진행 중이어서 건너뛰었습니다.", 0)
            except Exception:
                logging.exception("Scheduler loop failed")
            self.stop_event.wait(20)

    def _status_loop(self) -> None:
        while not self.stop_event.wait(self.config.status_refresh_interval):
            if not self.action_lock.locked():
                try:
                    status = self.refresh_status()
                    if status["online"]:
                        self.refresh_activity()
                except Exception:
                    logging.exception("Status refresh failed")

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .config import Config


class TrueNASAPIError(RuntimeError):
    pass


def get_api_key(config: Config) -> str | None:
    environment_key = os.environ.get("WOL_NAS_TRUENAS_API_KEY")
    if environment_key:
        return environment_key
    if not config.truenas_username:
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", config.keychain_service, "-a", config.truenas_username, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


@dataclass
class WebSocketClient:
    url: str
    verify_tls: bool = True
    timeout: float = 10.0

    def __post_init__(self) -> None:
        self.sock: socket.socket | None = None

    def __enter__(self) -> "WebSocketClient":
        parsed = urlparse(self.url)
        if parsed.scheme != "wss":
            raise TrueNASAPIError("TrueNAS 연결은 wss://만 허용됩니다.")
        host = parsed.hostname
        if not host:
            raise TrueNASAPIError("TrueNAS WebSocket 주소가 올바르지 않습니다.")
        port = parsed.port or 443
        raw = socket.create_connection((host, port), timeout=self.timeout)
        context = ssl.create_default_context()
        if not self.verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.sock = context.wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_http_headers()
        status = response.split("\r\n", 1)[0]
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if " 101 " not in status or f"sec-websocket-accept: {expected.lower()}" not in response.lower():
            self.close()
            raise TrueNASAPIError(f"WebSocket 연결 실패: {status}")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _read_http_headers(self) -> str:
        assert self.sock is not None
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        return data.decode("iso-8859-1")

    def send_json(self, payload: dict[str, Any]) -> None:
        assert self.sock is not None
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        mask = secrets.token_bytes(4)
        length = len(data)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def receive_json(self) -> dict[str, Any]:
        assert self.sock is not None
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
            if opcode == 0x8:
                raise TrueNASAPIError("TrueNAS가 연결을 종료했습니다.")
            if opcode == 0x9:
                self._send_control(0xA, data)
                continue
            if opcode == 0x1:
                return json.loads(data.decode("utf-8"))

    def call(self, request_id: int, method: str, params: list[Any]) -> Any:
        self.send_json({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            response = self.receive_json()
            if response.get("id") != request_id:
                continue
            if "error" in response:
                reason = response["error"].get("data", {}).get("reason") or response["error"].get("message") or "API 오류"
                raise TrueNASAPIError(str(reason))
            return response.get("result")

    def _send_control(self, opcode: int, data: bytes) -> None:
        assert self.sock is not None
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(data)]) + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        assert self.sock is not None
        data = bytearray()
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise TrueNASAPIError("TrueNAS 연결이 예기치 않게 끊겼습니다.")
            data.extend(chunk)
        return bytes(data)

    def close(self) -> None:
        if self.sock:
            try:
                self._send_control(0x8, b"")
            except OSError:
                pass
            self.sock.close()
            self.sock = None


def request_shutdown(config: Config, reason: str = "NAS Control 예약/수동 정상 종료") -> None:
    api_key = get_api_key(config)
    if not config.truenas_username or not api_key:
        raise TrueNASAPIError("TrueNAS 사용자명과 API 키를 먼저 설정하세요.")
    with WebSocketClient(config.truenas_ws_url, config.verify_truenas_tls) as client:
        login = client.call(
            1,
            "auth.login_ex",
            [{"mechanism": "API_KEY_PLAIN", "username": config.truenas_username, "api_key": api_key, "login_options": {"user_info": False}}],
        )
        if not isinstance(login, dict) or login.get("response_type") != "SUCCESS":
            raise TrueNASAPIError("TrueNAS API 인증에 실패했습니다.")
        client.call(2, "system.shutdown", [reason, {"delay": 0}])


def _login(client: WebSocketClient, config: Config, api_key: str) -> None:
    login = client.call(
        1,
        "auth.login_ex",
        [{"mechanism": "API_KEY_PLAIN", "username": config.truenas_username, "api_key": api_key, "login_options": {"user_info": False}}],
    )
    if not isinstance(login, dict) or login.get("response_type") != "SUCCESS":
        raise TrueNASAPIError("TrueNAS API 인증에 실패했습니다.")


def _safe_number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _open_count(lock: dict[str, Any]) -> int:
    opens = lock.get("opens")
    return max(1, len(opens)) if isinstance(opens, dict) else 1


def _normalized_share(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _summarize_smb(sessions: Any, shares: Any, locks: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    session_rows = sessions if isinstance(sessions, list) else []
    share_rows = shares if isinstance(shares, list) else []
    lock_rows = [row for row in locks] if isinstance(locks, list) else []
    session_by_id = {
        str(row.get("session_id")): row
        for row in session_rows if isinstance(row, dict) and row.get("session_id") is not None
    }
    safe_connections = []
    for share in share_rows:
        if not isinstance(share, dict) or str(share.get("service") or "").upper() == "IPC$":
            continue
        session = session_by_id.get(str(share.get("session_id")), {})
        safe_connections.append(
            {
                "session_id": str(share.get("session_id") or ""),
                "share": str(share.get("service") or "SMB 공유"),
                "client": str(share.get("machine") or session.get("remote_machine") or session.get("hostname") or "연결된 장치"),
                "username": str(session.get("username") or ""),
                "connected_at": str(share.get("connected_at") or session.get("creation_time") or ""),
            }
        )

    lock_rows = [row for row in lock_rows if isinstance(row, dict)]
    open_file_count = sum(_open_count(row) for row in lock_rows)
    backups: dict[tuple[str, str], dict[str, Any]] = {}
    for lock in lock_rows:
        filename = str(lock.get("filename") or "")
        match = re.search(r"(?:^|/)([^/]+)\.sparsebundle(?:/|$)", filename, re.IGNORECASE)
        if not match:
            continue
        bundle = match.group(1)
        service_path = str(lock.get("service_path") or "")
        key = (service_path, bundle.lower())
        item = backups.setdefault(
            key,
            {"name": bundle, "bundle": f"{bundle}.sparsebundle", "share": "Time Machine", "clients": [], "usernames": [], "open_files": 0},
        )
        item["open_files"] += _open_count(lock)
        path_key = _normalized_share(service_path.rsplit("/", 1)[-1])
        matching_connections = [row for row in safe_connections if _normalized_share(row["share"]) == path_key]
        if matching_connections:
            item["share"] = matching_connections[0]["share"]
        for connection in matching_connections:
            if connection["client"] not in item["clients"]:
                item["clients"].append(connection["client"])
            if connection["username"] and connection["username"] not in item["usernames"]:
                item["usernames"].append(connection["username"])
    return safe_connections, list(backups.values()), open_file_count


def summarize_activity(
    jobs: Any,
    pools: Any,
    sessions: Any,
    realtime: Any,
    smb_sessions: Any = None,
    smb_shares: Any = None,
    smb_locks: Any = None,
    disk_temperatures: Any = None,
    system_info: Any = None,
) -> dict[str, Any]:
    safe_jobs = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
        safe_jobs.append(
            {
                "id": job.get("id"),
                "method": str(job.get("method") or "작업"),
                "description": str(job.get("description") or progress.get("description") or "TrueNAS 작업"),
                "state": str(job.get("state") or "RUNNING"),
                "percent": _safe_number(progress.get("percent")),
            }
        )

    safe_pools = []
    active_scans = []
    for pool in pools if isinstance(pools, list) else []:
        if not isinstance(pool, dict):
            continue
        scan = pool.get("scan") if isinstance(pool.get("scan"), dict) else {}
        item = {
            "name": str(pool.get("name") or "스토리지"),
            "status": str(pool.get("status") or "UNKNOWN"),
            "size": _safe_number(pool.get("size")),
            "allocated": _safe_number(pool.get("allocated")),
            "free": _safe_number(pool.get("free")),
            "healthy": bool(pool.get("healthy", pool.get("status") == "ONLINE")),
            "scan": {
                "function": str(scan.get("function") or ""),
                "state": str(scan.get("state") or ""),
                "percent": _safe_number(scan.get("percentage")),
            },
        }
        safe_pools.append(item)
        if item["scan"]["state"] == "SCANNING":
            active_scans.append({"pool": item["name"], **item["scan"]})

    safe_sessions = []
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict):
            continue
        safe_sessions.append(
            {
                "target": str(session.get("target") or session.get("target_alias") or "iSCSI"),
                "client": str(session.get("initiator_addr") or session.get("initiator") or "연결된 장치"),
            }
        )

    fields = realtime if isinstance(realtime, dict) else {}
    cpu = fields.get("cpu") if isinstance(fields.get("cpu"), dict) else {}
    cpu_total = cpu.get("cpu") if isinstance(cpu.get("cpu"), dict) else {}
    memory = fields.get("memory") if isinstance(fields.get("memory"), dict) else {}
    disks = fields.get("disks") if isinstance(fields.get("disks"), dict) else {}
    interfaces = fields.get("interfaces") if isinstance(fields.get("interfaces"), dict) else {}
    online_interfaces = [value for value in interfaces.values() if isinstance(value, dict) and value.get("link_state") == "LINK_STATE_UP"]
    io = {
        "disk_read_bps": _safe_number(disks.get("read_bytes")),
        "disk_write_bps": _safe_number(disks.get("write_bytes")),
        "network_rx_bps": sum(_safe_number(item.get("received_bytes_rate")) for item in online_interfaces),
        "network_tx_bps": sum(_safe_number(item.get("sent_bytes_rate")) for item in online_interfaces),
    }
    smb_connections, time_machine_backups, smb_open_files = _summarize_smb(smb_sessions, smb_shares, smb_locks)
    smb_session_count = len({row["session_id"] for row in smb_connections if row["session_id"]})
    disk_temps = {
        str(name): _safe_number(value)
        for name, value in (disk_temperatures.items() if isinstance(disk_temperatures, dict) else [])
        if isinstance(value, (int, float))
    }
    cpu_temp = _safe_number(cpu_total.get("temp"))
    all_temperatures = [value for value in [cpu_temp, *disk_temps.values()] if value > 0]
    info = system_info if isinstance(system_info, dict) else {}
    memory_total = _safe_number(memory.get("physical_memory_total") or info.get("physmem"))
    memory_available = _safe_number(memory.get("physical_memory_available"))
    resources = {
        "cpu_percent": _safe_number(cpu_total.get("usage")),
        "cpu_model": str(info.get("model") or ""),
        "cpu_cores": int(_safe_number(info.get("cores"))),
        "load_average": [float(value) for value in info.get("loadavg", []) if isinstance(value, (int, float))][:3],
        "uptime_seconds": _safe_number(info.get("uptime_seconds")),
        "memory": {
            "total_bytes": memory_total,
            "available_bytes": memory_available,
            "used_bytes": max(0, memory_total - memory_available),
            "arc_bytes": _safe_number(memory.get("arc_size")),
        },
        "temperatures": {"cpu_c": cpu_temp or None, "max_c": max(all_temperatures) if all_temperatures else None, "disks": disk_temps},
    }
    return {
        "available": True,
        "checked_at": time.time(),
        "jobs": safe_jobs,
        "pools": safe_pools,
        "active_scans": active_scans,
        "iscsi_sessions": safe_sessions,
        "smb_connections": smb_connections,
        "time_machine_backups": time_machine_backups,
        "resources": resources,
        "io": io,
        "summary": {
            "active_jobs": len(safe_jobs),
            "active_scans": len(active_scans),
            "iscsi_sessions": len(safe_sessions),
            "smb_sessions": smb_session_count,
            "smb_open_files": smb_open_files,
            "time_machine_backups": len(time_machine_backups),
        },
    }


def fetch_activity(config: Config) -> dict[str, Any]:
    api_key = get_api_key(config)
    if not config.truenas_username or not api_key:
        raise TrueNASAPIError("TrueNAS API가 설정되지 않았습니다.")
    with WebSocketClient(config.truenas_ws_url, config.verify_truenas_tls, timeout=8) as client:
        _login(client, config, api_key)
        jobs = client.call(2, "core.get_jobs", [[["state", "in", ["WAITING", "RUNNING"]]], {"select": ["id", "method", "description", "state", "progress"]}])
        pools = client.call(3, "pool.query", [[], {"select": ["name", "status", "scan", "size", "allocated", "free", "healthy"]}])
        sessions = client.call(4, "iscsi.global.sessions", [])
        try:
            smb_sessions = client.call(5, "smb.status", ["SESSIONS"])
            smb_shares = client.call(6, "smb.status", ["SHARES"])
            smb_locks = client.call(7, "smb.status", ["LOCKS"])
        except TrueNASAPIError:
            smb_sessions, smb_shares, smb_locks = [], [], []
        try:
            disk_temperatures = client.call(8, "disk.temperatures", [])
        except TrueNASAPIError:
            disk_temperatures = {}
        try:
            system_info = client.call(9, "system.info", [])
        except TrueNASAPIError:
            system_info = {}
        collection = 'reporting.realtime:{"interval":2}'
        client.call(10, "core.subscribe", [collection])
        assert client.sock is not None
        client.sock.settimeout(6)
        realtime: dict[str, Any] = {}
        while True:
            message = client.receive_json()
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            if message.get("method") == "collection_update" and params.get("collection") == collection:
                realtime = params.get("fields") if isinstance(params.get("fields"), dict) else {}
                break
        return summarize_activity(jobs, pools, sessions, realtime, smb_sessions, smb_shares, smb_locks, disk_temperatures, system_info)

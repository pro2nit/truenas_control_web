from __future__ import annotations

import http.client
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .config import Config


def send_magic_packet(config: Config) -> int:
    mac_bytes = bytes.fromhex(config.mac_address.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(config.wol_repeat):
            for host in config.broadcasts:
                for port in config.wol_ports:
                    sock.sendto(packet, (host, int(port)))
                    sent += 1
            time.sleep(0.25)
    return sent


def ping(host: str, timeout: float = 1.0) -> bool:
    milliseconds = max(100, int(timeout * 1000))
    try:
        result = subprocess.run(
            ["/sbin/ping", "-c", "1", "-W", str(milliseconds), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def http_ready(host: str, port: int, timeout: float = 3.0) -> bool:
    connection = http.client.HTTPConnection(host, int(port), timeout=timeout)
    try:
        connection.request("GET", "/", headers={"User-Agent": "NAS-Control/1.0"})
        response = connection.getresponse()
        response.read(256)
        return response.status in {200, 301, 302, 303, 307, 308, 401, 403}
    except OSError:
        return False
    finally:
        connection.close()


def check_status(config: Config) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            "ping": pool.submit(ping, config.nas_ip),
            "web_ui": pool.submit(tcp_open, config.nas_ip, config.web_ui_port),
            "smb": pool.submit(tcp_open, config.nas_ip, config.smb_port),
        }
        if config.nextcloud_port:
            futures["nextcloud"] = pool.submit(http_ready, config.nas_ip, config.nextcloud_port)
    checks = {name: future.result() for name, future in futures.items()}
    checks["nextcloud"] = checks.get("nextcloud") if config.nextcloud_port else None
    online = checks["ping"] or checks["web_ui"] or checks["smb"]
    ready = online and checks["web_ui"] and checks["smb"] and (checks["nextcloud"] is not False)
    return {"online": online, "ready": ready, "checks": checks, "checked_at": time.time()}


def wait_until(check: Callable[[], bool], timeout: int, interval: int, on_tick: Callable[[float], None] | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        if on_tick:
            on_tick(max(0, deadline - time.monotonic()))
        time.sleep(interval)
    return False

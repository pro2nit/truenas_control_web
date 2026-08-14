from __future__ import annotations

import json
import ipaddress
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass
class Config:
    nas_ip: str = "192.168.1.100"
    mac_address: str = "00:11:22:33:44:55"
    broadcasts: list[str] = field(default_factory=lambda: ["192.168.1.255", "255.255.255.255"])
    wol_ports: list[int] = field(default_factory=lambda: [9, 7])
    wol_repeat: int = 10
    wol_retry_after: int = 60
    ping_timeout: int = 240
    service_timeout: int = 120
    nextcloud_timeout: int = 180
    check_interval: int = 5
    status_refresh_interval: int = 15
    web_ui_port: int = 80
    smb_port: int = 445
    nextcloud_port: int = 0
    truenas_ws_url: str = "wss://192.168.1.100/api/current"
    truenas_username: str = ""
    verify_truenas_tls: bool = True
    timezone: str = "UTC"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8787
    keychain_service: str = "truenas-control-web-api-key"

    @classmethod
    def load(cls, path: Path) -> "Config":
        config = cls()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {key: value for key, value in raw.items() if hasattr(config, key)}
            for key, value in known.items():
                setattr(config, key, value)
        config.validate()
        return config

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def public_dict(self, api_key_configured: bool) -> dict[str, Any]:
        return {
            "nas_ip": self.nas_ip,
            "mac_address": self.mac_address,
            "broadcasts": self.broadcasts,
            "timezone": self.timezone,
            "truenas_ws_url": self.truenas_ws_url,
            "truenas_username": self.truenas_username,
            "verify_truenas_tls": self.verify_truenas_tls,
            "api_key_configured": api_key_configured,
            "listen": f"{self.listen_host}:{self.listen_port}",
        }

    def validate(self) -> None:
        nas_address = ipaddress.ip_address(self.nas_ip)
        if nas_address.version != 4:
            raise ValueError("NAS 주소는 IPv4 주소여야 합니다.")
        mac = self.mac_address.replace(":", "").replace("-", "")
        if len(mac) != 12:
            raise ValueError("MAC 주소 형식이 올바르지 않습니다.")
        bytes.fromhex(mac)
        for broadcast in self.broadcasts:
            if ipaddress.ip_address(broadcast).version != 4:
                raise ValueError("브로드캐스트 주소는 IPv4 주소여야 합니다.")
        if self.listen_host not in {"localhost", "::1"}:
            address = ipaddress.ip_address(self.listen_host)
            tailscale_network = ipaddress.ip_network("100.64.0.0/10")
            if not address.is_loopback and address not in tailscale_network:
                raise ValueError("웹 서비스는 loopback 또는 Tailscale IPv4 주소에서만 수신해야 합니다.")
        if not (1 <= int(self.listen_port) <= 65535):
            raise ValueError("웹 서비스 포트가 올바르지 않습니다.")
        for name, port, allow_disabled in (
            ("TrueNAS Web UI", self.web_ui_port, False),
            ("SMB", self.smb_port, False),
            ("추가 HTTP 서비스", self.nextcloud_port, True),
        ):
            minimum = 0 if allow_disabled else 1
            if not (minimum <= int(port) <= 65535):
                raise ValueError(f"{name} 포트가 올바르지 않습니다.")
        if not self.truenas_ws_url.startswith("wss://"):
            raise ValueError("TrueNAS API 키 보호를 위해 wss:// 주소만 허용됩니다.")
        ZoneInfo(self.timezone)

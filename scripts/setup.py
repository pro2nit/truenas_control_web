#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from nas_control.config import Config


def ask(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def ask_int(label: str, default: int, allow_zero: bool = False) -> int:
    while True:
        raw = ask(label, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("숫자로 입력하세요.")
            continue
        if (allow_zero and value == 0) or 1 <= value <= 65535:
            return value
        print("0 또는 1~65535 범위의 포트를 입력하세요." if allow_zero else "1~65535 범위의 포트를 입력하세요.")


def detected_timezone() -> str:
    try:
        target = Path("/etc/localtime").resolve()
        marker = "/zoneinfo/"
        if marker in str(target):
            return str(target).split(marker, 1)[1]
    except OSError:
        pass
    return "UTC"


def main() -> None:
    parser = argparse.ArgumentParser(description="NAS Control 기본 설정")
    parser.add_argument("--listen-host", help="설치 스크립트가 감지한 Tailscale IPv4 주소")
    args = parser.parse_args()

    data_dir = Path(os.environ.get("WOL_NAS_DATA_DIR", Path.home() / "Library/Application Support/NAS Control"))
    config_path = data_dir / "config.json"
    config = Config.load(config_path)

    if args.listen_host:
        config.listen_host = args.listen_host
        config.save(config_path)
        return

    print("NAS Control 기본 설정")
    print("NAS의 고정 IPv4 주소와 유선 LAN 인터페이스의 MAC 주소가 필요합니다.")
    nas_ip = ask("TrueNAS IPv4 주소", config.nas_ip)
    network = ipaddress.ip_network(f"{nas_ip}/24", strict=False)
    suggested_broadcast = str(network.broadcast_address)
    config.nas_ip = nas_ip
    config.mac_address = ask("Wake-on-LAN MAC 주소", config.mac_address)
    broadcast = ask("브로드캐스트 IPv4 주소", suggested_broadcast)
    config.broadcasts = [broadcast, "255.255.255.255"] if broadcast != "255.255.255.255" else [broadcast]
    config.web_ui_port = ask_int("TrueNAS Web UI 포트", config.web_ui_port)
    config.smb_port = ask_int("SMB 포트", config.smb_port)
    config.nextcloud_port = ask_int("추가 HTTP 서비스 포트 (사용하지 않으면 0)", config.nextcloud_port, allow_zero=True)
    config.timezone = ask("시간대", detected_timezone())
    config.truenas_ws_url = f"wss://{nas_ip}/api/current"
    config.save(config_path)
    print(f"기본 설정을 저장했습니다: {config_path}")


if __name__ == "__main__":
    main()

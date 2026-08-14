#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from nas_control.config import Config


def main() -> None:
    data_dir = Path(os.environ.get("WOL_NAS_DATA_DIR", Path.home() / "Library/Application Support/NAS Control"))
    config_path = data_dir / "config.json"
    config = Config.load(config_path)
    print("TrueNAS API 설정")
    print("API 키 인증은 HTTPS/WSS가 필요합니다. TrueNAS 인증서를 먼저 구성하세요.")
    username = input(f"TrueNAS 사용자명 [{config.truenas_username or 'admin'}]: ").strip() or config.truenas_username or "admin"
    ws_url = input(f"WebSocket 주소 [{config.truenas_ws_url}]: ").strip() or config.truenas_ws_url
    api_key = getpass.getpass("TrueNAS API 키: ").strip()
    if not api_key:
        raise SystemExit("API 키가 비어 있습니다.")
    config.truenas_username = username
    config.truenas_ws_url = ws_url
    config.save(config_path)
    subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-U", "-s", config.keychain_service, "-a", username, "-w", api_key],
        check=True,
    )
    print("API 키를 macOS Keychain에 저장했습니다. scripts/install.sh를 다시 실행하면 서비스가 재시작됩니다.")


if __name__ == "__main__":
    main()

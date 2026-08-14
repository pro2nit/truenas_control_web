#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
label="io.github.truenas-control-web"
agent_dir="$HOME/Library/LaunchAgents"
agent_path="$agent_dir/$label.plist"
install_root="$HOME/Library/Application Support/NAS Control"
runtime_dir="$install_root/app"
log_dir="$HOME/Library/Logs"
template_path="$project_dir/launchd/$label.plist"
python_bin="$(command -v python3 || true)"

if [[ -z "$python_bin" ]]; then
  print -u2 "Python 3를 찾을 수 없습니다. Python 3.11 이상을 먼저 설치하세요."
  exit 1
fi
if ! "$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  print -u2 "Python 3.11 이상이 필요합니다."
  exit 1
fi

tailscale_bin="$(command -v tailscale || true)"
if [[ -z "$tailscale_bin" && -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
  tailscale_bin="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
fi
if [[ -z "$tailscale_bin" ]]; then
  print -u2 "Tailscale CLI를 찾을 수 없습니다. Tailscale 앱을 설치하고 로그인하세요."
  exit 1
fi

/bin/mkdir -p "$agent_dir" "$install_root" "$log_dir"
config_path="$install_root/config.json"
if [[ ! -f "$config_path" ]]; then
  WOL_NAS_DATA_DIR="$install_root" "$python_bin" "$project_dir/scripts/setup.py"
fi

tailscale_ip=$("$tailscale_bin" ip -4 | /usr/bin/head -n 1)
if [[ "$tailscale_ip" != 100.* ]]; then
  print -u2 "Tailscale IPv4 주소를 확인할 수 없습니다. Tailscale 로그인 상태를 확인하세요."
  exit 1
fi
WOL_NAS_DATA_DIR="$install_root" "$python_bin" "$project_dir/scripts/setup.py" --listen-host "$tailscale_ip"

/bin/rm -rf "$runtime_dir.new"
/bin/mkdir -p "$runtime_dir.new"
/usr/bin/ditto "$project_dir/app.py" "$runtime_dir.new/app.py"
/usr/bin/ditto "$project_dir/nas_control" "$runtime_dir.new/nas_control"
/usr/bin/ditto "$project_dir/static" "$runtime_dir.new/static"
WOL_NAS_DATA_DIR="$install_root" "$python_bin" "$runtime_dir.new/app.py" --check-config >/dev/null
/bin/rm -rf "$runtime_dir.old"
if [[ -d "$runtime_dir" ]]; then
  /bin/mv "$runtime_dir" "$runtime_dir.old"
fi
/bin/mv "$runtime_dir.new" "$runtime_dir"
/bin/rm -rf "$runtime_dir.old"

escape_sed() { print -r -- "$1" | /usr/bin/sed 's/[&|]/\\&/g'; }
python_escaped=$(escape_sed "$python_bin")
runtime_escaped=$(escape_sed "$runtime_dir")
install_escaped=$(escape_sed "$install_root")
log_escaped=$(escape_sed "$log_dir")
/usr/bin/sed \
  -e "s|__PYTHON_BIN__|$python_escaped|g" \
  -e "s|__RUNTIME_DIR__|$runtime_escaped|g" \
  -e "s|__INSTALL_ROOT__|$install_escaped|g" \
  -e "s|__LOG_DIR__|$log_escaped|g" \
  "$template_path" > "$agent_path"
/bin/chmod 600 "$agent_path"
/usr/bin/plutil -lint "$agent_path" >/dev/null

/bin/launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
for attempt in {1..20}; do
  if ! /bin/launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 0.25
done
/bin/launchctl bootstrap "gui/$(id -u)" "$agent_path"
/bin/launchctl enable "gui/$(id -u)/$label"
/bin/launchctl kickstart -k "gui/$(id -u)/$label"

listen_port=$(WOL_NAS_DATA_DIR="$install_root" "$python_bin" -c 'from pathlib import Path; import os, sys; sys.path.insert(0, os.path.join(os.environ["WOL_NAS_DATA_DIR"], "app")); from nas_control.config import Config; print(Config.load(Path(os.environ["WOL_NAS_DATA_DIR"]) / "config.json").listen_port)')
print "NAS Control 설치 완료"
print "접속 주소: http://$tailscale_ip:$listen_port"
print "Tailscale Serve와 Funnel은 사용하지 않습니다."

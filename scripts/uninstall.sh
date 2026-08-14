#!/bin/zsh
set -euo pipefail

label="io.github.truenas-control-web"
agent_path="$HOME/Library/LaunchAgents/$label.plist"

/bin/launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
[[ ! -f "$agent_path" ]] || /bin/rm "$agent_path"
print "서비스를 제거했습니다. 설정과 기록은 ~/Library/Application Support/NAS Control 에 남아 있습니다."

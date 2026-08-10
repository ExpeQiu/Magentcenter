#!/usr/bin/env bash
# 卸载自启动（launchd + 登录项 + 看门狗）
set -euo pipefail

UID_NUM=$(id -u)
launchctl bootout "gui/$UID_NUM/com.agentcenter.backend" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/com.agentcenter.frontend" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.backend.plist"
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.frontend.plist"

# 停止看门狗
launchctl remove com.agentcenter.watchdog 2>/dev/null || true
pkill -f "AgentCenter/watchdog.sh" 2>/dev/null || true
/usr/bin/screen -S agentcenter-watchdog -X quit 2>/dev/null || true

# 移除登录项
osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "System Events"
  repeat with li in login items
    if path of li contains "AgentCenter/login-start.sh" then delete li
  end repeat
end tell
APPLESCRIPT

rm -rf "$HOME/Library/Application Support/AgentCenter"
echo "[daemon] 已卸载自启动"

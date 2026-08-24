#!/usr/bin/env bash
# AgentCenter 一键启动（后端 + 前端）
# 委托 start-detached.sh：用 screen 脱离 Cursor Agent 会话，避免进程被回收导致 ERR_CONNECTION_REFUSED
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/AgentCenter"
LOG_DIR="${AGENTCENTER_LOG_DIR:-$HOME/Library/Logs/AgentCenter}"

mkdir -p "$LOG_DIR"

echo "[start-all] 使用 screen 持久启动（不受 Agent 会话回收影响）..."
"$ROOT/scripts/start-detached.sh"

# 若已安装登录自启，确保看门狗在跑（KeepAlive plist，避免 submit 作业睡死）
WATCHDOG_PLIST="$HOME/Library/LaunchAgents/com.agentcenter.watchdog.plist"
if [[ -x "$APP_SUPPORT/watchdog.sh" ]]; then
  if ! pgrep -f "$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
    UID_NUM=$(id -u)
    if [[ -f "$WATCHDOG_PLIST" ]] && command -v launchctl >/dev/null 2>&1; then
      launchctl remove com.agentcenter.watchdog 2>/dev/null || true
      launchctl bootout "gui/$UID_NUM/com.agentcenter.watchdog" 2>/dev/null || true
      launchctl bootstrap "gui/$UID_NUM" "$WATCHDOG_PLIST" 2>/dev/null || \
        launchctl kickstart -k "gui/$UID_NUM/com.agentcenter.watchdog" 2>/dev/null || true
    elif command -v launchctl >/dev/null 2>&1; then
      launchctl remove com.agentcenter.watchdog 2>/dev/null || true
      launchctl submit -l com.agentcenter.watchdog -- \
        /bin/bash "$APP_SUPPORT/watchdog.sh" \
        >> "$LOG_DIR/watchdog.log" 2>&1 || true
    fi
    if ! pgrep -f "$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
      /usr/bin/screen -S agentcenter-watchdog -X quit 2>/dev/null || true
      /usr/bin/screen -dmS agentcenter-watchdog /bin/bash "$APP_SUPPORT/watchdog.sh"
    fi
    echo "[start-all] 看门狗已拉起"
  fi
fi

"$ROOT/scripts/status.sh"

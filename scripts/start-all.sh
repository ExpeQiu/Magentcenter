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

# 若已安装登录自启，确保看门狗在跑（从本机 Application Support 拉起）
if [[ -x "$APP_SUPPORT/watchdog.sh" ]]; then
  if ! pgrep -f "$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
    # 通过 launchctl 提交到用户会话，避免挂在 Agent 进程树下
    if command -v launchctl >/dev/null 2>&1; then
      launchctl remove com.agentcenter.watchdog 2>/dev/null || true
      launchctl submit -l com.agentcenter.watchdog -- \
        /bin/bash "$APP_SUPPORT/watchdog.sh" \
        >> "$LOG_DIR/watchdog.log" 2>&1 || true
    fi
    if ! pgrep -f "$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
      # fallback：screen 会话保活看门狗
      screen -S agentcenter-watchdog -X quit 2>/dev/null || true
      screen -dmS agentcenter-watchdog /bin/bash "$APP_SUPPORT/watchdog.sh"
    fi
    echo "[start-all] 看门狗已拉起"
  fi
fi

"$ROOT/scripts/status.sh"

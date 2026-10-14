#!/usr/bin/env bash
# AgentCenter 停止脚本（后端 + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8013}"
"$ROOT/scripts/stop-frontend.sh" 2>/dev/null || true

APP_SUPPORT="${HOME}/Library/Application Support/AgentCenter"
PID_FILE="${AGENTCENTER_DATA_DIR:-$APP_SUPPORT/data}/agentcenter.pid"
LEGACY_PID="$ROOT/logs/agentcenter.pid"
if [[ ! -f "$PID_FILE" && -f "$LEGACY_PID" ]]; then
  PID_FILE="$LEGACY_PID"
fi

UID_NUM=$(id -u)
if launchctl print "gui/$UID_NUM/com.agentcenter.backend" >/dev/null 2>&1; then
  echo "[stop] 停止登录自启的节点服务"
  launchctl bootout "gui/$UID_NUM/com.agentcenter.backend" 2>/dev/null || true
fi

if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "[stop] 停止节点服务 PID=$PID"
    kill "$PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID" 2>/dev/null || true
    fi
    echo "[stop] 已停止"
  else
    echo "[stop] 进程不存在 PID=$PID"
  fi
  rm -f "$PID_FILE"
else
  echo "[stop] 没有记录中的节点服务。端口 $PORT 上的其他进程不会被结束。"
fi

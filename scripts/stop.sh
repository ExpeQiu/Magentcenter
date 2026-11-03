#!/usr/bin/env bash
# AgentCenter 停止脚本（Core + Node Agent + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib-pids.sh"

PORT="${PORT:-8013}"
"$ROOT/scripts/stop-frontend.sh" 2>/dev/null || true

APP_SUPPORT="${HOME}/Library/Application Support/AgentCenter"
export AGENTCENTER_DATA_DIR="${AGENTCENTER_DATA_DIR:-$APP_SUPPORT/data}"

UID_NUM=$(id -u)
if launchctl print "gui/$UID_NUM/com.agentcenter.backend" >/dev/null 2>&1; then
  echo "[stop] 停止登录自启的节点服务"
  launchctl bootout "gui/$UID_NUM/com.agentcenter.backend" 2>/dev/null || true
fi
if launchctl print "gui/$UID_NUM/com.agentcenter.node-agent" >/dev/null 2>&1; then
  echo "[stop] 停止登录自启的 Node Agent"
  launchctl bootout "gui/$UID_NUM/com.agentcenter.node-agent" 2>/dev/null || true
fi

_ac_stop_all_local "$ROOT"
echo "[stop] 本地服务已按 PID 文件停止。端口 $PORT 上非本目录登记的进程不会被结束。"

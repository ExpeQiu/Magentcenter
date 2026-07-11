#!/usr/bin/env bash
# AgentCenter 停止脚本（后端 + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/stop-frontend.sh" 2>/dev/null || true

PID_FILE="$ROOT/logs/agentcenter.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "[stop] AgentCenter 未运行（无 PID 文件）"
  exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
  echo "[stop] 停止 AgentCenter PID=$PID"
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

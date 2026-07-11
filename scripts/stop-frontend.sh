#!/usr/bin/env bash
# AgentCenter 前端停止脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/logs/frontend.pid"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"

pids=$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$pids" ]]; then
  echo "[stop-frontend] 停止端口 $FRONTEND_PORT 进程: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
  pids=$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null || true)
  [[ -z "$pids" ]] || kill -9 $pids 2>/dev/null || true
  echo "[stop-frontend] 已停止"
else
  echo "[stop-frontend] 前端未运行（端口 $FRONTEND_PORT 无监听）"
fi
rm -f "$PID_FILE"

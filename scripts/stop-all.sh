#!/usr/bin/env bash
# 停止所有 AgentCenter 服务（screen + 端口）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8013}"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"

screen -S agentcenter-api -X quit 2>/dev/null || true
screen -S agentcenter-web -X quit 2>/dev/null || true

"$ROOT/scripts/stop.sh" 2>/dev/null || true
"$ROOT/scripts/stop-frontend.sh" 2>/dev/null || true

for p in "$PORT" "$FRONTEND_PORT"; do
  pids=$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
  fi
done

echo "[stop-all] 已停止"

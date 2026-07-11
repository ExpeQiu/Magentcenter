#!/usr/bin/env bash
# AgentCenter 前端启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
PID_FILE="$ROOT/logs/frontend.pid"
LOG_FILE="$ROOT/logs/frontend.log"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
NEXT_BIN="$FRONTEND/node_modules/.bin/next"

_stop_by_port() {
  local pids
  pids=$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "[frontend] 停止端口 $FRONTEND_PORT 上的进程: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null || true)
    [[ -z "$pids" ]] || kill -9 $pids 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
}

cd "$FRONTEND"
mkdir -p "$ROOT/logs"

if [[ ! -d node_modules ]]; then
  echo "[frontend] 安装依赖..."
  npm install --cache /tmp/npm-cache-agentcenter 2>&1 | tail -5
fi

if [[ ! -x "$NEXT_BIN" ]]; then
  echo "[frontend] 错误: next 未安装，请运行 npm install"
  exit 1
fi

_stop_by_port

echo "[frontend] 启动 Next.js (host=$FRONTEND_HOST port=$FRONTEND_PORT)..."
nohup "$NEXT_BIN" dev -p "$FRONTEND_PORT" -H "$FRONTEND_HOST" \
  >> "$LOG_FILE" 2>&1 </dev/null &
disown 2>/dev/null || true

for i in $(seq 1 30); do
  if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    pid=$(lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null | head -1)
    echo "$pid" > "$PID_FILE"
    # 再等编译就绪
    sleep 2
    if curl -sf --max-time 5 "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1; then
      echo "[frontend] 已启动 PID=$pid"
      echo "[frontend] http://localhost:$FRONTEND_PORT"
      echo "[frontend] http://127.0.0.1:$FRONTEND_PORT"
      exit 0
    fi
  fi
  sleep 1
done

echo "[frontend] 启动失败：端口 $FRONTEND_PORT 不可用"
tail -20 "$LOG_FILE" 2>/dev/null || true
exit 1

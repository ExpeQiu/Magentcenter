#!/usr/bin/env bash
# AgentCenter 启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PID_FILE="$ROOT/logs/agentcenter.pid"
LOG_FILE="$ROOT/logs/agentcenter.log"

cd "$ROOT"
mkdir -p logs data

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ ! -d "$VENV" ]]; then
  echo "[start] 创建 Python 虚拟环境..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q -r "$BACKEND/requirements.txt"

PORT="${PORT:-8013}"
HOST="${HOST:-0.0.0.0}"

# 按端口停止旧进程
pids=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$pids" ]]; then
  echo "[start] 停止端口 $PORT 上的进程: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
fi
rm -f "$PID_FILE"

echo "[start] 启动 AgentCenter API (host=$HOST port=$PORT)..."
cd "$BACKEND"
# 子 shell + nohup 脱离当前终端，避免会话结束时被杀掉
(
  nohup "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" \
    >> "$LOG_FILE" 2>&1 </dev/null &
  echo $! > "$PID_FILE"
  disown -a 2>/dev/null || true
)

# 等待端口就绪
for i in $(seq 1 15); do
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    pid=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
    echo "$pid" > "$PID_FILE"
    echo "[start] AgentCenter 已启动 PID=$pid"
    echo "[start] API: http://localhost:$PORT/api/health"
    echo "[start] 日志: $LOG_FILE"
    exit 0
  fi
  sleep 1
done

echo "[start] 启动失败，查看日志: $LOG_FILE"
tail -15 "$LOG_FILE" 2>/dev/null || true
exit 1

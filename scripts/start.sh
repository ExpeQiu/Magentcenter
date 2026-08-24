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

# 已导出的环境变量优先于 .env（便于 verify 强制 AI_MOCK_MODE=true）
_PRESERVE_AI_MOCK_MODE="${AI_MOCK_MODE-__UNSET__}"
_PRESERVE_RUNTIMES="${RUNTIMES-__UNSET__}"
_PRESERVE_DEFAULT_RUNTIME="${DEFAULT_RUNTIME-__UNSET__}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ "$_PRESERVE_AI_MOCK_MODE" != "__UNSET__" ]]; then
  export AI_MOCK_MODE="$_PRESERVE_AI_MOCK_MODE"
fi
if [[ "$_PRESERVE_RUNTIMES" != "__UNSET__" ]]; then
  export RUNTIMES="$_PRESERVE_RUNTIMES"
fi
if [[ "$_PRESERVE_DEFAULT_RUNTIME" != "__UNSET__" ]]; then
  export DEFAULT_RUNTIME="$_PRESERVE_DEFAULT_RUNTIME"
fi
unset _PRESERVE_AI_MOCK_MODE _PRESERVE_RUNTIMES _PRESERVE_DEFAULT_RUNTIME

if [[ ! -d "$VENV" ]]; then
  echo "[start] 创建 Python 虚拟环境..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q -r "$BACKEND/requirements.txt"

PORT="${PORT:-8013}"
HOST="${HOST:-127.0.0.1}"

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
nohup "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" \
  >> "$LOG_FILE" 2>&1 </dev/null &
echo $! > "$PID_FILE"
disown 2>/dev/null || true

# 等待端口就绪并验证 health
for i in $(seq 1 20); do
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    pid=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
    echo "$pid" > "$PID_FILE"
    if curl -sf --max-time 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      echo "[start] AgentCenter 已启动 PID=$pid"
      echo "[start] API: http://localhost:$PORT/api/health"
      echo "[start] 日志: $LOG_FILE"
      exit 0
    fi
  fi
  sleep 1
done

echo "[start] 启动失败，查看日志: $LOG_FILE"
tail -15 "$LOG_FILE" 2>/dev/null || true
exit 1

#!/usr/bin/env bash
# AgentCenter 启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
APP_SUPPORT="${HOME}/Library/Application Support/AgentCenter"
export AGENTCENTER_DATA_DIR="${AGENTCENTER_DATA_DIR:-$APP_SUPPORT/data}"
export AGENTCENTER_LOG_DIR="${AGENTCENTER_LOG_DIR:-$HOME/Library/Logs/AgentCenter}"
mkdir -p "$AGENTCENTER_DATA_DIR" "$AGENTCENTER_LOG_DIR" "$ROOT/logs"
if [[ ! -f "$AGENTCENTER_DATA_DIR/agentcenter.db" && -f "$BACKEND/data/agentcenter.db" ]]; then
  cp "$BACKEND/data/agentcenter.db" "$AGENTCENTER_DATA_DIR/agentcenter.db"
  echo "[start] 数据库已复制到本机应用目录"
fi
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///${AGENTCENTER_DATA_DIR}/agentcenter.db}"
PID_FILE="$AGENTCENTER_DATA_DIR/agentcenter.pid"
LOG_FILE="$AGENTCENTER_LOG_DIR/agentcenter.log"

cd "$ROOT"

# 已导出的环境变量优先于 .env（便于 verify 强制 AI_MOCK_MODE=true）
_PRESERVE_AI_MOCK_MODE="${AI_MOCK_MODE-__UNSET__}"
_PRESERVE_RUNTIMES="${RUNTIMES-__UNSET__}"
_PRESERVE_DEFAULT_RUNTIME="${DEFAULT_RUNTIME-__UNSET__}"
_PRESERVE_DATABASE_URL="${DATABASE_URL-__UNSET__}"
_PRESERVE_DATA_DIR="${AGENTCENTER_DATA_DIR-__UNSET__}"
_PRESERVE_LOG_DIR="${AGENTCENTER_LOG_DIR-__UNSET__}"

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
if [[ "$_PRESERVE_DATABASE_URL" != "__UNSET__" ]]; then
  export DATABASE_URL="$_PRESERVE_DATABASE_URL"
fi
if [[ "$_PRESERVE_DATA_DIR" != "__UNSET__" ]]; then
  export AGENTCENTER_DATA_DIR="$_PRESERVE_DATA_DIR"
fi
if [[ "$_PRESERVE_LOG_DIR" != "__UNSET__" ]]; then
  export AGENTCENTER_LOG_DIR="$_PRESERVE_LOG_DIR"
fi
unset _PRESERVE_AI_MOCK_MODE _PRESERVE_RUNTIMES _PRESERVE_DEFAULT_RUNTIME
unset _PRESERVE_DATABASE_URL _PRESERVE_DATA_DIR _PRESERVE_LOG_DIR

if [[ ! -d "$VENV" ]]; then
  echo "[start] 创建 Python 虚拟环境..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "[start] 首次安装依赖..."
  pip install -q -r "$BACKEND/requirements.txt"
else
  echo "[start] 使用已安装依赖"
fi

PORT="${PORT:-8013}"
HOST="${HOST:-127.0.0.1}"

if curl -sf --max-time 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "[start] 节点服务已在运行，不重复启动"
  exit 0
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[start] 端口 $PORT 已被占用，但健康检查未通过。启动不会按端口结束占用进程。"
  exit 1
fi

echo "[start] 启动 AgentCenter API (host=$HOST port=$PORT profile=${DEPLOY_PROFILE:-full})..."
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

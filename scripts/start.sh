#!/usr/bin/env bash
# AgentCenter 启动脚本：本地核心（+ 可选 Node Agent）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/lib-pids.sh"

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
LOG_FILE="$AGENTCENTER_LOG_DIR/agentcenter.log"
NODE_LOG="$AGENTCENTER_LOG_DIR/node-agent.log"

cd "$ROOT"

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
  echo "[start] 节点服务已在运行，不重复启动 Core"
else
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[start] 端口 $PORT 已被占用，但健康检查未通过。启动不会按端口结束占用进程。"
    exit 1
  fi

  echo "[start] 启动 AgentCenter API (host=$HOST port=$PORT profile=${DEPLOY_PROFILE:-full})..."
  cd "$BACKEND"
  nohup "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" \
    >> "$LOG_FILE" 2>&1 </dev/null &
  _ac_write_pid core $!
  disown 2>/dev/null || true

  for i in $(seq 1 20); do
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      pid=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
      _ac_write_pid core "$pid"
      if curl -sf --max-time 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        echo "[start] Core 已启动 PID=$pid"
        echo "[start] API: http://localhost:$PORT/api/health"
        echo "[start] 日志: $LOG_FILE"
        break
      fi
    fi
    if [[ "$i" -eq 20 ]]; then
      echo "[start] 启动失败，查看日志: $LOG_FILE"
      tail -15 "$LOG_FILE" 2>/dev/null || true
      exit 1
    fi
    sleep 1
  done
fi

# 可选拉起 Node Agent
START_NODE_AGENT="${START_NODE_AGENT:-auto}"
want_node=0
case "$(echo "$START_NODE_AGENT" | tr '[:upper:]' '[:lower:]')" in
  on|1|true|yes) want_node=1 ;;
  off|0|false|no) want_node=0 ;;
  *)
    if [[ -n "${FLEET_ENROLL_TOKEN:-}" ]]; then
      want_node=1
    fi
    ;;
esac

if [[ "$want_node" -eq 1 ]]; then
  if [[ -f "$AGENTCENTER_DATA_DIR/node-agent.pid" ]] && kill -0 "$(tr -d '[:space:]' <"$AGENTCENTER_DATA_DIR/node-agent.pid")" 2>/dev/null; then
    echo "[start] Node Agent 已在运行"
  else
    echo "[start] 拉起 Node Agent…"
    export AGENTCENTER_URL="${AGENTCENTER_URL:-http://127.0.0.1:$PORT}"
    nohup "$ROOT/scripts/run-node-agent.sh" >>"$NODE_LOG" 2>&1 </dev/null &
    _ac_write_pid node-agent $!
    disown 2>/dev/null || true
    echo "[start] Node Agent PID=$(tr -d '[:space:]' <"$AGENTCENTER_DATA_DIR/node-agent.pid") 日志=$NODE_LOG"
  fi
else
  echo "[start] 跳过 Node Agent（设 START_NODE_AGENT=on 且配置 FLEET_ENROLL_TOKEN 可启用）"
fi

exit 0

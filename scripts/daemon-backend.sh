#!/usr/bin/env bash
# launchd 后端 wrapper：等待项目目录挂载后再启动
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PYTHON="$VENV/bin/python"
LOG_DIR="${AGENTCENTER_LOG_DIR:-$HOME/Library/Logs/AgentCenter}"
LOG="$LOG_DIR/daemon-backend.log"
PORT="${PORT:-8013}"
HOST="${HOST:-127.0.0.1}"
MAX_WAIT=120

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [daemon-backend] $*" >> "$LOG"; }

log "starting wrapper ROOT=$ROOT"

for ((i=0; i<MAX_WAIT; i++)); do
  if [[ -x "$PYTHON" ]]; then
    break
  fi
  log "waiting for mount ($((i+1))/${MAX_WAIT}s)..."
  sleep 1
done

if [[ ! -x "$PYTHON" ]]; then
  log "ERROR: python not found at $PYTHON after ${MAX_WAIT}s"
  exit 78
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PORT="${PORT:-8013}"
HOST="${HOST:-127.0.0.1}"

log "exec uvicorn host=$HOST port=$PORT"
cd "$BACKEND"
exec "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT"

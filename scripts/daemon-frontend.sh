#!/usr/bin/env bash
# launchd 前端 wrapper：等待项目目录挂载后再启动
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
NEXT_JS="$FRONTEND/node_modules/next/dist/bin/next"
NODE_BIN="$(command -v node || echo /opt/homebrew/bin/node)"
LOG_DIR="${AGENTCENTER_LOG_DIR:-$HOME/Library/Logs/AgentCenter}"
LOG="$LOG_DIR/daemon-frontend.log"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"
MAX_WAIT=120

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [daemon-frontend] $*" >> "$LOG"; }

log "starting wrapper ROOT=$ROOT"

for ((i=0; i<MAX_WAIT; i++)); do
  if [[ -f "$NEXT_JS" && -x "$NODE_BIN" ]]; then
    break
  fi
  log "waiting for mount ($((i+1))/${MAX_WAIT}s)..."
  sleep 1
done

if [[ ! -f "$NEXT_JS" ]]; then
  log "ERROR: next not found at $NEXT_JS after ${MAX_WAIT}s"
  exit 78
fi

log "exec next dev port=$FRONTEND_PORT"
cd "$FRONTEND"
exec "$NODE_BIN" "$NEXT_JS" dev -p "$FRONTEND_PORT" -H 0.0.0.0

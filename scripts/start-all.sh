#!/usr/bin/env bash
# AgentCenter 一键启动（后端 + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8013}"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"
APP_SUPPORT="$HOME/Library/Application Support/AgentCenter"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

wait_health() {
  local url="$1" label="$2" max="${3:-30}"
  for ((i=1; i<=max; i++)); do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo "[start-all] $label 就绪 (${i}s)"
      return 0
    fi
    sleep 1
  done
  echo "[start-all] $label 启动超时: $url"
  return 1
}

echo "[start-all] 启动后端..."
"$ROOT/scripts/start.sh"
wait_health "http://127.0.0.1:$PORT/api/health" "Backend"

echo "[start-all] 启动前端..."
"$ROOT/scripts/start-frontend.sh"
wait_health "http://127.0.0.1:$FRONTEND_PORT/" "Frontend"

# 验证 API 代理（system 页依赖此接口）
if wait_health "http://127.0.0.1:$FRONTEND_PORT/api/health" "API Proxy" 15; then
  echo "[start-all] API 代理正常"
else
  echo "[start-all] WARN: API 代理未就绪，请检查 next.config.ts rewrites"
fi

# 若已安装登录自启，确保看门狗在跑
if [[ -x "$APP_SUPPORT/watchdog.sh" ]]; then
  if ! pgrep -f "$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
    LOG_DIR="${AGENTCENTER_LOG_DIR:-$HOME/Library/Logs/AgentCenter}"
    mkdir -p "$LOG_DIR"
    nohup /bin/bash "$APP_SUPPORT/watchdog.sh" >> "$LOG_DIR/watchdog.log" 2>&1 &
    echo "[start-all] 看门狗已重启 pid=$!"
  fi
fi

"$ROOT/scripts/status.sh"

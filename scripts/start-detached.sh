#!/usr/bin/env bash
# 在 screen 会话中持久启动（不受 Cursor 终端会话影响）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PORT="${PORT:-8013}"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"

# 加载 .env
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# 停止旧 screen 会话
screen -S agentcenter-api -X quit 2>/dev/null || true
screen -S agentcenter-web -X quit 2>/dev/null || true
sleep 1

# 按端口清理残留
for p in "$PORT" "$FRONTEND_PORT"; do
  pids=$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
  [[ -z "$pids" ]] || kill $pids 2>/dev/null || true
done
sleep 1

mkdir -p "$ROOT/logs"

# dev 模式前清理 .next，避免 build 与 dev 混用导致 chunk 缺失
if [[ -d "$FRONTEND/.next" ]]; then
  echo "[detached] 清理 frontend/.next 缓存…"
  rm -rf "$FRONTEND/.next"
fi

# 后端
screen -dmS agentcenter-api bash -c "
  cd '$BACKEND' && \
  source '$VENV/bin/activate' && \
  exec uvicorn app.main:app --host 0.0.0.0 --port $PORT \
    >> '$ROOT/logs/agentcenter.log' 2>&1
"

# 前端
screen -dmS agentcenter-web bash -c "
  cd '$FRONTEND' && \
  exec ./node_modules/.bin/next dev -p $FRONTEND_PORT -H $FRONTEND_HOST \
    >> '$ROOT/logs/frontend.log' 2>&1
"

echo "[detached] 已在 screen 会话中启动服务"
echo "[detached] 查看: screen -r agentcenter-api / screen -r agentcenter-web"
echo "[detached] 停止: ./scripts/stop-all.sh"

# 等待就绪
for i in $(seq 1 30); do
  api_ok=false
  web_ok=false
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && api_ok=true
  curl -sf "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1 && web_ok=true
  if $api_ok && $web_ok; then
    echo "[detached] 全部就绪"
    echo "[detached] API:  http://127.0.0.1:$PORT"
    echo "[detached] 前端: http://127.0.0.1:$FRONTEND_PORT"
    echo ""
    echo "⚠️  请勿用 Cursor 内置浏览器，请用 Safari/Chrome 打开上述地址"
    open "http://127.0.0.1:$FRONTEND_PORT" 2>/dev/null || true
    exit 0
  fi
  sleep 1
done

echo "[detached] 启动超时，查看日志:"
tail -5 "$ROOT/logs/agentcenter.log" 2>/dev/null
tail -5 "$ROOT/logs/frontend.log" 2>/dev/null
exit 1

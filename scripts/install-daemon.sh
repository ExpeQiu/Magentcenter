#!/usr/bin/env bash
# 安装登录自启 + 看门狗（适用于外置盘项目）
# 注意：launchctl 作业无法执行 /Volumes 上的 .sh（Operation not permitted），
# 重启逻辑必须落在 ~/Library/Application Support/AgentCenter/。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/AgentCenter"
LOG_DIR="$HOME/Library/Logs/AgentCenter"
LOGIN_SCRIPT="$APP_SUPPORT/login-start.sh"
ENV_FILE="$ROOT/.env"

mkdir -p "$APP_SUPPORT" "$LOG_DIR" "$ROOT/logs"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
fi

PORT="${PORT:-8013}"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"

# 卸载旧 launchd plist（外置盘上不可靠）
UID_NUM=$(id -u)
launchctl bootout "gui/$UID_NUM/com.agentcenter.backend" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/com.agentcenter.frontend" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.backend.plist"
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.frontend.plist"

cat > "$APP_SUPPORT/launch-backend.sh" <<SCRIPT
#!/bin/bash
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
ROOT="$ROOT"
PYTHON="$ROOT/backend/.venv/bin/python"
LOG="$LOG_DIR/launch-backend.log"
MAX_WAIT=180

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [launch-backend] \$*" >> "\$LOG"; }
log "triggered"

for ((i=0; i<MAX_WAIT; i++)); do
  [[ -x "\$PYTHON" ]] && break
  sleep 2
done
[[ -x "\$PYTHON" ]] || { log "ERROR: python not found"; exit 78; }

HOST="\${HOST:-0.0.0.0}"
PORT="\${PORT:-$PORT}"

log "exec uvicorn port=\$PORT"
cd "\$ROOT/backend" || { log "ERROR: cd failed"; exit 78; }
exec "\$PYTHON" -m uvicorn app.main:app --host "\$HOST" --port "\$PORT"
SCRIPT

cat > "$APP_SUPPORT/launch-frontend.sh" <<SCRIPT
#!/bin/bash
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/opt/node@22/bin"
ROOT="$ROOT"
NEXT_JS="$ROOT/frontend/node_modules/next/dist/bin/next"
NODE_BIN="/opt/homebrew/opt/node@22/bin/node"
[[ -x "\$NODE_BIN" ]] || NODE_BIN="\$(command -v node || true)"
LOG="$LOG_DIR/launch-frontend.log"
MAX_WAIT=180

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [launch-frontend] \$*" >> "\$LOG"; }
log "triggered"

for ((i=0; i<MAX_WAIT; i++)); do
  [[ -f "\$NEXT_JS" ]] && break
  sleep 2
done
[[ -f "\$NEXT_JS" ]] || { log "ERROR: next not found"; exit 78; }
[[ -x "\$NODE_BIN" ]] || { log "ERROR: node not found"; exit 78; }

PORT="\${FRONTEND_PORT:-$FRONTEND_PORT}"
log "exec next dev port=\$PORT"
cd "\$ROOT/frontend" || { log "ERROR: cd failed"; exit 78; }
exec "\$NODE_BIN" "\$NEXT_JS" dev -p "\$PORT" -H 0.0.0.0
SCRIPT

cat > "$APP_SUPPORT/restart.sh" <<SCRIPT
#!/bin/bash
# 仅使用本机 Application Support 脚本；禁止直接执行 /Volumes 上的 .sh
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
APP_SUPPORT="$APP_SUPPORT"
LOG="$LOG_DIR/restart.log"
PORT="$PORT"
FRONTEND_PORT="$FRONTEND_PORT"
SCREEN="/usr/bin/screen"

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [restart] \$*" >> "\$LOG"; }
log "begin"

"\$SCREEN" -S agentcenter-api -X quit 2>/dev/null || true
"\$SCREEN" -S agentcenter-web -X quit 2>/dev/null || true
sleep 1

for p in "\$PORT" "\$FRONTEND_PORT"; do
  pids=\$(lsof -tiTCP:"\$p" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "\$pids" ]]; then
    kill \$pids 2>/dev/null || true
  fi
done
sleep 1

"\$SCREEN" -dmS agentcenter-api /bin/bash "\$APP_SUPPORT/launch-backend.sh"
"\$SCREEN" -dmS agentcenter-web /bin/bash "\$APP_SUPPORT/launch-frontend.sh"
log "screen submitted"

api_ok=false
web_ok=false
for i in \$(seq 1 60); do
  api_ok=false
  web_ok=false
  curl -sf --max-time 2 "http://127.0.0.1:\$PORT/api/health" >/dev/null 2>&1 && api_ok=true
  curl -sf --max-time 2 "http://127.0.0.1:\$FRONTEND_PORT/" >/dev/null 2>&1 && web_ok=true
  if \$api_ok && \$web_ok; then
    log "ready"
    exit 0
  fi
  sleep 1
done

log "timeout api=\$api_ok web=\$web_ok"
exit 1
SCRIPT

cat > "$APP_SUPPORT/login-start.sh" <<SCRIPT
#!/bin/bash
# 登录后启动 AgentCenter（本机脚本，可访问外置盘二进制）
ROOT="$ROOT"
APP_SUPPORT="$APP_SUPPORT"
LOG="$LOG_DIR/login-start.log"
MAX_WAIT=180

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [login-start] \$*" >> "\$LOG"; }

log "triggered, waiting for ROOT..."
for ((i=0; i<MAX_WAIT; i++)); do
  [[ -d "\$ROOT/backend" ]] && break
  sleep 2
done
if [[ ! -d "\$ROOT/backend" ]]; then
  log "ERROR: project not mounted after \${MAX_WAIT}s"
  exit 1
fi

log "starting services via Application Support restart.sh"
/bin/bash "\$APP_SUPPORT/restart.sh" >> "\$LOG" 2>&1 || log "restart failed"

# 看门狗：launchctl submit（勿挂在登录脚本进程树下）
launchctl remove com.agentcenter.watchdog 2>/dev/null || true
launchctl submit -l com.agentcenter.watchdog -- /bin/bash "\$APP_SUPPORT/watchdog.sh" \
  >> "$LOG_DIR/watchdog.log" 2>&1 || true
if ! pgrep -f "\$APP_SUPPORT/watchdog.sh" >/dev/null 2>&1; then
  /usr/bin/screen -dmS agentcenter-watchdog /bin/bash "\$APP_SUPPORT/watchdog.sh"
fi
log "watchdog ensured"
SCRIPT

cat > "$APP_SUPPORT/watchdog.sh" <<SCRIPT
#!/bin/bash
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
ROOT="$ROOT"
APP_SUPPORT="$APP_SUPPORT"
LOG="$LOG_DIR/watchdog.log"
PORT="$PORT"
FRONTEND_PORT="$FRONTEND_PORT"
INTERVAL=60

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [watchdog] \$*" >> "\$LOG"; }
log "watchdog running"

while true; do
  sleep "\$INTERVAL"
  [[ -d "\$ROOT/backend" ]] || { log "project unmounted, skip"; continue; }
  api_ok=false
  web_ok=false
  curl -sf --max-time 5 "http://127.0.0.1:\$PORT/api/health" >/dev/null 2>&1 && api_ok=true
  curl -sf --max-time 5 "http://127.0.0.1:\$FRONTEND_PORT/" >/dev/null 2>&1 && web_ok=true
  if \$api_ok && \$web_ok; then
    continue
  fi
  log "service down api=\$api_ok web=\$web_ok, restarting..."
  # 必须调用本机 restart.sh；直接执行 /Volumes/.../*.sh 会 Operation not permitted
  /bin/bash "\$APP_SUPPORT/restart.sh" >> "\$LOG" 2>&1 || log "restart failed"
done
SCRIPT

chmod +x "$APP_SUPPORT/login-start.sh" "$APP_SUPPORT/watchdog.sh" \
  "$APP_SUPPORT/restart.sh" "$APP_SUPPORT/launch-backend.sh" "$APP_SUPPORT/launch-frontend.sh"

# 注册 macOS 登录项
osascript <<APPLESCRIPT
tell application "System Events"
  set found to false
  repeat with li in login items
    if path of li is "$LOGIN_SCRIPT" then set found to true
  end repeat
  if not found then
    make login item at end with properties {path:"$LOGIN_SCRIPT", hidden:true}
  end if
end tell
APPLESCRIPT

# 立即启动（本机脚本）
nohup /bin/bash "$APP_SUPPORT/login-start.sh" >> "$LOG_DIR/login-start.log" 2>&1 &

echo "[login] 已安装登录自启 + 看门狗（重启走 Application Support）"
echo "[login] 后端: http://127.0.0.1:$PORT"
echo "[login] 前端: http://127.0.0.1:$FRONTEND_PORT"
echo "[login] 日志: $LOG_DIR/"
echo "[login] 卸载: ./scripts/uninstall-daemon.sh"
sleep 8
"$ROOT/scripts/status.sh"

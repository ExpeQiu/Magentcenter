#!/usr/bin/env bash
# 安装登录自启 + 看门狗（适用于外置盘项目，launchd 无法访问 /Volumes）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_SUPPORT="$HOME/Library/Application Support/AgentCenter"
LOG_DIR="$HOME/Library/Logs/AgentCenter"
LOGIN_NAME="AgentCenter"
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

# 卸载 launchd（外置盘上不可靠）
UID_NUM=$(id -u)
launchctl bootout "gui/$UID_NUM/com.agentcenter.backend" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/com.agentcenter.frontend" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.backend.plist"
rm -f "$HOME/Library/LaunchAgents/com.agentcenter.frontend.plist"

cat > "$APP_SUPPORT/login-start.sh" <<SCRIPT
#!/bin/bash
# 登录后启动 AgentCenter（用户会话，可访问外置盘）
ROOT="$ROOT"
LOG="$LOG_DIR/login-start.log"
MAX_WAIT=180

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [login-start] \$*" >> "\$LOG"; }

log "triggered, waiting for ROOT..."
for ((i=0; i<MAX_WAIT; i++)); do
  [[ -d "\$ROOT/scripts" ]] && break
  sleep 2
done
if [[ ! -d "\$ROOT/scripts" ]]; then
  log "ERROR: project not mounted after \${MAX_WAIT}s"
  exit 1
fi

log "starting services"
/bin/bash "\$ROOT/scripts/start-all.sh" >> "\$LOG" 2>&1

# 看门狗：每 60s 检查，挂掉则重启
nohup /bin/bash "$APP_SUPPORT/watchdog.sh" >> "$LOG_DIR/watchdog.log" 2>&1 &
log "watchdog started pid=\$!"
SCRIPT

cat > "$APP_SUPPORT/watchdog.sh" <<SCRIPT
#!/bin/bash
ROOT="$ROOT"
LOG="$LOG_DIR/watchdog.log"
PORT="$PORT"
FRONTEND_PORT="$FRONTEND_PORT"
INTERVAL=60

log() { echo "\$(date '+%Y-%m-%d %H:%M:%S') [watchdog] \$*" >> "\$LOG"; }
log "watchdog running"

while true; do
  sleep "\$INTERVAL"
  [[ -d "\$ROOT/scripts" ]] || { log "project unmounted, skip"; continue; }
  api_ok=false
  web_ok=false
  curl -sf --max-time 5 "http://127.0.0.1:\$PORT/api/health" >/dev/null 2>&1 && api_ok=true
  curl -sf --max-time 5 "http://127.0.0.1:\$FRONTEND_PORT/" >/dev/null 2>&1 && web_ok=true
  if \$api_ok && \$web_ok; then
    continue
  fi
  log "service down api=\$api_ok web=\$web_ok, restarting..."
  /bin/bash "\$ROOT/scripts/start-all.sh" >> "\$LOG" 2>&1 || log "restart failed"
done
SCRIPT

chmod +x "$APP_SUPPORT/login-start.sh" "$APP_SUPPORT/watchdog.sh"

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

# 立即启动
nohup /bin/bash "$APP_SUPPORT/login-start.sh" >> "$LOG_DIR/login-start.log" 2>&1 &

echo "[login] 已安装登录自启 + 看门狗"
echo "[login] 后端: http://127.0.0.1:$PORT"
echo "[login] 前端: http://127.0.0.1:$FRONTEND_PORT"
echo "[login] 日志: $LOG_DIR/"
echo "[login] 卸载: ./scripts/uninstall-daemon.sh"
sleep 8
"$ROOT/scripts/status.sh"

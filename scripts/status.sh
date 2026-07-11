#!/usr/bin/env bash
# AgentCenter 服务状态检查
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8013}"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"

check_port() {
  local name="$1" port="$2" url="$3"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    local pid
    pid=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo "[OK]   $name  port=$port pid=$pid  $url"
    else
      echo "[WARN] $name  port=$port pid=$pid  监听中但 HTTP 无响应"
    fi
  else
    echo "[DOWN] $name  port=$port  未监听"
  fi
}

echo "=== AgentCenter 状态 ==="

UID_NUM=$(id -u)
if launchctl print "gui/$UID_NUM/com.agentcenter.backend" >/dev/null 2>&1; then
  echo "[DAEMON] launchd 已安装"
elif osascript -e "tell application \"System Events\" to repeat with li in login items
  if path of li contains \"AgentCenter/login-start.sh\" then return \"yes\"
end repeat
return \"no\"" 2>/dev/null | grep -q yes; then
  echo "[DAEMON] 登录自启已安装（外置盘模式）"
else
  echo "[DAEMON] 未安装 — 运行 ./scripts/install-daemon.sh 启用开机自启"
fi

check_port "Backend " "$PORT" "http://127.0.0.1:$PORT/api/health"
check_port "Frontend" "$FRONTEND_PORT" "http://127.0.0.1:$FRONTEND_PORT/"

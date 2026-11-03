#!/usr/bin/env bash
# 发布云端协调器到自建 Linux 单机。
# 本机构建静态前端 → rsync 代码 → 远端 venv/systemd → health。
# 明确不调用 sync-waytoai.sh。日志：logs/deploy-cloud.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${AGENTCENTER_LOG_DIR_LOCAL:-$ROOT/logs}"
LOG_FILE="$LOG_DIR/deploy-cloud.log"
REMOTE="${AGENTCENTER_CLOUD_HOST:-root@47.113.225.93}"
REMOTE_BASE="${AGENTCENTER_CLOUD_BASE:-/opt/agentcenter}"
REMOTE_APP="$REMOTE_BASE/app"
SKIP_FRONTEND="${SKIP_FRONTEND_BUILD:-0}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
RSYNC=(rsync -az --delete --timeout=120)
MW="$ROOT/frontend/src/middleware.ts"
MW_BAK="$ROOT/frontend/src/middleware.ts.cloud-deploy-bak"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [deploy-cloud] $*"; }

restore_middleware() {
  if [[ -f "$MW_BAK" ]]; then
    mv -f "$MW_BAK" "$MW"
    log "restored frontend middleware"
  fi
}
trap restore_middleware EXIT

log "begin remote=$REMOTE app=$REMOTE_APP root=$ROOT"
export COPYFILE_DISABLE=1

# --- 静态前端 ---
if [[ "$SKIP_FRONTEND" == "1" && -f "$ROOT/frontend/out/index.html" ]]; then
  log "skip frontend build (SKIP_FRONTEND_BUILD=1)"
else
  log "build Next static export"
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    (cd "$ROOT/frontend" && npm install)
  fi
  if [[ -f "$MW" ]]; then
    mv "$MW" "$MW_BAK"
    log "parked middleware for static export"
  fi
  (cd "$ROOT/frontend" && AGENTCENTER_PACKAGING=1 npm run build)
  restore_middleware
  trap restore_middleware EXIT
  if [[ ! -f "$ROOT/frontend/out/index.html" ]]; then
    log "ERROR frontend out/index.html missing"
    exit 1
  fi
  CSS_COUNT="$(find "$ROOT/frontend/out" -name '*.css' | wc -l | tr -d ' ')"
  if [[ "${CSS_COUNT:-0}" -lt 1 ]]; then
    log "ERROR frontend CSS missing"
    exit 1
  fi
  log "frontend ready css=$CSS_COUNT"
fi

# --- 远端目录 ---
log "ensure remote dirs"
"${SSH[@]}" "$REMOTE" "mkdir -p '$REMOTE_APP' '$REMOTE_BASE/data' '$REMOTE_BASE/logs' '$REMOTE_BASE/backups'"

# --- rsync 代码（排除本地数据/密钥/缓存）---
log "rsync backend"
"${RSYNC[@]}" \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'data' \
  --exclude '*.pyc' \
  --exclude '.env' \
  "$ROOT/backend/" "$REMOTE:$REMOTE_APP/backend/"

log "rsync guide"
"${RSYNC[@]}" \
  --exclude 'guide from codex/*.html' \
  "$ROOT/guide/" "$REMOTE:$REMOTE_APP/guide/"

log "rsync frontend out + cloud unit/env example"
"${SSH[@]}" "$REMOTE" "mkdir -p '$REMOTE_APP/frontend/out' '$REMOTE_APP/scripts/cloud'"
"${RSYNC[@]}" "$ROOT/frontend/out/" "$REMOTE:$REMOTE_APP/frontend/out/"
"${RSYNC[@]}" \
  "$ROOT/scripts/cloud/env.cloud.example" \
  "$ROOT/scripts/cloud/agentcenter-cloud.service" \
  "$REMOTE:$REMOTE_APP/scripts/cloud/"

# --- 远端：迁移旧布局、venv、.env、停旧进程、systemd ---
log "remote provision"
"${SSH[@]}" "$REMOTE" bash -s <<'REMOTE_EOF'
set -euo pipefail
BASE=/opt/agentcenter
APP="$BASE/app"
BACKEND="$APP/backend"
ENV_FILE="$APP/.env"
LEGACY_ENV="$BASE/.env"
EXAMPLE="$APP/scripts/cloud/env.cloud.example"
UNIT_SRC="$APP/scripts/cloud/agentcenter-cloud.service"
UNIT_DST=/etc/systemd/system/agentcenter-cloud.service

cd "$BACKEND"
NEED_VENV=0
if [[ ! -x .venv/bin/python ]]; then
  NEED_VENV=1
elif head -1 .venv/bin/uvicorn 2>/dev/null | grep -q "$BASE/backend/"; then
  NEED_VENV=1
elif grep -q "$BASE/backend/" .venv/pyvenv.cfg 2>/dev/null; then
  NEED_VENV=1
fi
if [[ "$NEED_VENV" == "1" ]]; then
  echo "[remote] (re)creating app-local venv"
  rm -rf .venv
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

if [[ ! -f "$ENV_FILE" && -f "$LEGACY_ENV" ]]; then
  cp -a "$LEGACY_ENV" "$ENV_FILE"
  echo "[remote] migrated legacy .env -> app/.env"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE" "$ENV_FILE"
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  if grep -q '^FLEET_ENROLL_TOKEN=' "$ENV_FILE"; then
    sed -i "s|^FLEET_ENROLL_TOKEN=.*|FLEET_ENROLL_TOKEN=$TOKEN|" "$ENV_FILE"
  else
    echo "FLEET_ENROLL_TOKEN=$TOKEN" >> "$ENV_FILE"
  fi
  mkdir -p "$BASE/backups"
  echo "generated FLEET_ENROLL_TOKEN at $(date -Iseconds)" > "$BASE/backups/LAST_ENV_NOTE.txt"
  echo "token written only in $ENV_FILE" >> "$BASE/backups/LAST_ENV_NOTE.txt"
  echo "[remote] created .env from example"
fi

if grep -q '^DEPLOY_PROFILE=' "$ENV_FILE"; then
  sed -i 's|^DEPLOY_PROFILE=.*|DEPLOY_PROFILE=cloud|' "$ENV_FILE"
else
  echo 'DEPLOY_PROFILE=cloud' >> "$ENV_FILE"
fi
if grep -q '^LOCAL_EXECUTOR_SCAN=' "$ENV_FILE"; then
  sed -i 's|^LOCAL_EXECUTOR_SCAN=.*|LOCAL_EXECUTOR_SCAN=off|' "$ENV_FILE"
else
  echo 'LOCAL_EXECUTOR_SCAN=off' >> "$ENV_FILE"
fi
for key in KNOWLEDGE_WIKI_DIR SKILLS_DIR HERMES_SKILLS_DIR SKILLS_CATALOG_DIR OUTPUTS_VAULT_ROOT OUTPUTS_VAULT_EXTRA; do
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=|" "$ENV_FILE"
  else
    echo "${key}=" >> "$ENV_FILE"
  fi
done
# 绝对 SQLite 路径保持指向共享 data 目录
if ! grep -q '^DATABASE_URL=' "$ENV_FILE"; then
  echo 'DATABASE_URL=sqlite+aiosqlite:////opt/agentcenter/data/agentcenter.db' >> "$ENV_FILE"
fi

CR="$BASE/data/content_roots.json"
if [[ -f "$CR" ]]; then
  if grep -Eiq 'Mobile Documents|iCloud|/Users/|/opt/agentcenter/WaytoAI' "$CR"; then
    mv "$CR" "$CR.bak-waytoai-$(date +%Y%m%d%H%M%S)"
    echo '{}' > "$CR"
    echo "[remote] quarantined WaytoAI/personal content_roots.json"
  fi
fi

echo "[remote] stop AgentCenter listeners on :8080"
systemctl stop agentcenter-cloud.service 2>/dev/null || true
# 旧扁平布局 /opt/agentcenter/backend 与 app 布局进程都清掉，避免 health 误判
for pid in $(ss -lntp 2>/dev/null | sed -n 's/.*:8080.*pid=\([0-9]*\).*/\1/p' | sort -u); do
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  case "$cmd" in
    *agentcenter*)
      echo "[remote] killing pid=$pid cmd=$cmd"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      ;;
  esac
done
# 再扫一遍残留
pkill -f '/opt/agentcenter/.*/uvicorn app.main:app' 2>/dev/null || true
pkill -f '/opt/agentcenter/.*/python -m uvicorn app.main:app' 2>/dev/null || true
sleep 1
if ss -lntp 2>/dev/null | grep -q ':8080'; then
  echo "[remote] WARN 8080 still busy after cleanup:"
  ss -lntp | grep 8080 || true
fi

install -m 644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable agentcenter-cloud.service
systemctl restart agentcenter-cloud.service

for i in $(seq 1 40); do
  if ! systemctl is-active agentcenter-cloud.service >/dev/null 2>&1; then
    sleep 1
    continue
  fi
  main_pid="$(systemctl show -p MainPID --value agentcenter-cloud.service 2>/dev/null || true)"
  cmd="$(tr '\0' ' ' < "/proc/${main_pid}/cmdline" 2>/dev/null || true)"
  case "$cmd" in
    */opt/agentcenter/app/backend/*) ;;
    *)
      sleep 1
      continue
      ;;
  esac
  if curl -sf --max-time 3 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    echo "[remote] health ok pid=$main_pid"
    curl -sf http://127.0.0.1:8080/api/health
    echo
    systemctl is-active agentcenter-cloud.service || true
    exit 0
  fi
  sleep 1
done
echo "[remote] ERROR health failed or wrong binary still bound"
systemctl status agentcenter-cloud.service --no-pager -l | head -50 || true
journalctl -u agentcenter-cloud -n 50 --no-pager || true
ss -lntp | grep 8080 || true
exit 1
REMOTE_EOF

log "public health check"
HOST_ONLY="${REMOTE##*@}"
for i in $(seq 1 15); do
  if curl -sf --max-time 5 "http://${HOST_ONLY}:8080/api/health" | grep -q '"status"'; then
    curl -sf "http://${HOST_ONLY}:8080/api/health"
    echo
    log "done"
    exit 0
  fi
  sleep 1
done
log "ERROR public health failed url=http://${HOST_ONLY}:8080/api/health"
exit 1

#!/usr/bin/env bash
# 远端一致性备份：SQLite / node_identity / .env
# 兼容旧布局 /opt/agentcenter/.env 与新布局 /opt/agentcenter/app/.env
# 日志：logs/backup-cloud.log
# 不调用 sync-waytoai.sh。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${AGENTCENTER_LOG_DIR_LOCAL:-$ROOT/logs}"
LOG_FILE="$LOG_DIR/backup-cloud.log"
REMOTE="${AGENTCENTER_CLOUD_HOST:-root@47.113.225.93}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
STAMP="$(date '+%Y%m%d-%H%M%S')"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [backup-cloud] $*"; }

log "begin remote=$REMOTE stamp=$STAMP"
"${SSH[@]}" "$REMOTE" bash -s <<EOF
set -euo pipefail
BASE=/opt/agentcenter
DEST="\$BASE/backups/$STAMP"
mkdir -p "\$DEST"
if [[ -f "\$BASE/data/agentcenter.db" ]]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "\$BASE/data/agentcenter.db" ".backup '\$DEST/agentcenter.db'" || cp -a "\$BASE/data/agentcenter.db" "\$DEST/agentcenter.db"
  else
    cp -a "\$BASE/data/agentcenter.db" "\$DEST/agentcenter.db"
  fi
fi
[[ -f "\$BASE/data/node_identity.json" ]] && cp -a "\$BASE/data/node_identity.json" "\$DEST/" || true
[[ -f "\$BASE/app/.env" ]] && cp -a "\$BASE/app/.env" "\$DEST/env" || true
[[ -f "\$BASE/.env" ]] && cp -a "\$BASE/.env" "\$DEST/env.legacy" || true
[[ -f "\$BASE/data/content_roots.json" ]] && cp -a "\$BASE/data/content_roots.json" "\$DEST/" || true
[[ -f "\$BASE/data/entry_code" ]] && cp -a "\$BASE/data/entry_code" "\$DEST/" || true
[[ -f "\$BASE/data/super_ai.json" ]] && cp -a "\$BASE/data/super_ai.json" "\$DEST/" || true
# 记录旧进程
ss -lntp 2>/dev/null | grep ':8080' > "\$DEST/listen-8080.txt" || true
ps aux | grep '[u]vicorn app.main:app' > "\$DEST/uvicorn-ps.txt" || true
printf '%s\n' "stamp=$STAMP host=\$(hostname) at=\$(date -Iseconds)" > "\$DEST/README.txt"
# 完整性校验
missing=0
[[ -f "\$DEST/agentcenter.db" ]] || { echo "MISSING agentcenter.db"; missing=1; }
[[ -f "\$DEST/node_identity.json" ]] || echo "WARN missing node_identity.json"
[[ -f "\$DEST/env" || -f "\$DEST/env.legacy" ]] || echo "WARN missing env"
if [[ -f "\$DEST/agentcenter.db" ]] && command -v sqlite3 >/dev/null 2>&1; then
  check=\$(sqlite3 "\$DEST/agentcenter.db" 'PRAGMA integrity_check;' | head -1)
  echo "integrity_check=\$check"
  [[ "\$check" == "ok" ]] || { echo "DB integrity failed"; missing=1; }
fi
ls -la "\$DEST"
if [[ "\$missing" -ne 0 ]]; then
  echo "BACKUP_VERIFY_FAIL \$DEST"
  exit 1
fi
echo "BACKUP_OK \$DEST"
EOF

log "done"

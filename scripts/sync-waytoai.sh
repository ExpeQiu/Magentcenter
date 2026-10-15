#!/usr/bin/env bash
# 可选的人工镜像：把本机 WaytoAI 拷到另一台机器。
# 不属于云端协调器（DEPLOY_PROFILE=cloud）。不要 --install 进云端注册流程，
# 也不要把目标目录写进云端 content_roots.json。
# 日志：logs/sync-waytoai.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${AGENTCENTER_LOG_DIR:-$ROOT/logs}"
LOG_FILE="$LOG_DIR/sync-waytoai.log"
SRC="${WAYTOAI_SRC:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI}"
REMOTE="${WAYTOAI_REMOTE:-root@47.113.225.93}"
DEST="${WAYTOAI_DEST:-/opt/agentcenter/WaytoAI}"
INTERVAL="${WAYTOAI_SYNC_INTERVAL:-900}"
PLIST="$HOME/Library/LaunchAgents/com.agentcenter.waytoai-sync.plist"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [sync-waytoai] $*" | tee -a "$LOG_FILE"; }

install_agent() {
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.agentcenter.waytoai-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/sync-waytoai.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>$INTERVAL</integer>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$LOG_FILE</string>
  <key>StandardErrorPath</key>
  <string>$LOG_FILE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF
  UID_NUM=$(id -u)
  launchctl bootout "gui/$UID_NUM/com.agentcenter.waytoai-sync" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$PLIST"
  log "installed interval=${INTERVAL}s plist=$PLIST"
}

if [[ "${1:-}" == "--install" ]]; then
  install_agent
  exit 0
fi

if [[ ! -d "$SRC" ]]; then
  log "ERROR source missing path=$SRC"
  exit 1
fi

LOCK_DIR="$LOG_DIR/sync-waytoai.lockdir"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "skip already running lock=$LOCK_DIR"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

log "begin src=$SRC dest=$REMOTE:$DEST"
"${SSH[@]}" "$REMOTE" "mkdir -p '$DEST'"

export COPYFILE_DISABLE=1
RSYNC_EXCLUDES=(
  --exclude '.DS_Store'
  --exclude '.git/'
  --exclude '.npm-cache/'
  --exclude '.next/'
  --exclude '__pycache__/'
  --exclude 'node_modules/'
  --exclude '.venv/'
  --exclude 'venv/'
  --exclude 'dist/'
  --exclude 'target/'
  --exclude 'vendor/'
  --exclude '*的替身'
  --exclude '*.pyc'
)
# 先传文档，云端技能页不用等大资源下完。
sync_docs() {
  local name="$1"
  if [[ ! -e "$SRC/$name" ]]; then
    log "skip missing name=$name"
    return 0
  fi
  "${SSH[@]}" "$REMOTE" "mkdir -p '$DEST/$name'" </dev/null
  log "docs start name=$name"
  set +e
  rsync -a --timeout=60 --prune-empty-dirs \
    --exclude 'node_modules/' \
    --exclude 'vendor/' \
    --exclude '.git/' \
    --exclude '.next/' \
    --exclude '.npm-cache/' \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude 'dist/' \
    --exclude '__pycache__/' \
    --include '*/' \
    --include '*.md' \
    --include '*.yml' \
    --include '*.yaml' \
    --include '*.json' \
    --exclude '*' \
    -e "${SSH[*]}" \
    "$SRC/$name/" "$REMOTE:$DEST/$name/" </dev/null
  local code=$?
  set -e
  if [[ "$code" -ne 0 ]]; then
    log "WARN docs name=$name exit=$code"
  else
    log "docs synced name=$name"
  fi
}

sync_one() {
  local name="$1"
  local from="$SRC/$name/"
  if [[ ! -e "$SRC/$name" ]]; then
    log "skip missing name=$name"
    return 0
  fi
  "${SSH[@]}" "$REMOTE" "mkdir -p '$DEST/$name'" </dev/null
  log "tree start name=$name"
  set +e
  rsync -a --delete --timeout=30 "${RSYNC_EXCLUDES[@]}" \
    -e "${SSH[*]}" \
    "$from" "$REMOTE:$DEST/$name/" </dev/null
  local code=$?
  set -e
  if [[ "$code" -ne 0 ]]; then
    log "WARN rsync name=$name exit=$code"
  else
    log "synced name=$name"
  fi
}

sync_docs personalwiki
sync_docs skills
sync_one personalwiki
sync_one skills
while IFS= read -r name; do
  [[ "$name" == "personalwiki" || "$name" == "skills" || "$name" == ".DS_Store" ]] && continue
  sync_one "$name"
done < <(find "$SRC" -mindepth 1 -maxdepth 1 -exec basename {} \;)

log "done"

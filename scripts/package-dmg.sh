#!/usr/bin/env bash
# 将 AgentCenter 打包为 Tauri 2 官方 macOS DMG。
# Next 静态页 + FastAPI sidecar；密钥不进包。
# 日志：logs/package-dmg.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/desktop"
TAURI="$DESKTOP/src-tauri"
RUNTIME="$TAURI/runtime"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/package-dmg.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

PYTHON_TAG="${PYTHON_STANDALONE_TAG:-20260610}"
PYTHON_VERSION="${PYTHON_STANDALONE_VERSION:-3.12.13}"
MW="$ROOT/frontend/src/middleware.ts"
MW_BAK="$ROOT/frontend/src/middleware.ts.packaging-bak"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$STAMP] [package-dmg] $*"; }

restore_middleware() {
  if [[ -f "$MW_BAK" ]]; then
    mv -f "$MW_BAK" "$MW"
    log "restored frontend middleware"
  fi
}
trap restore_middleware EXIT

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *)
    log "ERROR: unsupported arch=$ARCH"
    exit 1
    ;;
esac

log "begin root=$ROOT arch=$ARCH mode=tauri2"
cd "$ROOT"
export COPYFILE_DISABLE=1

if [[ ! -f "$TAURI/icons/icon.icns" ]]; then
  mkdir -p "$TAURI/icons"
  cp "$DESKTOP/build/icon.icns" "$TAURI/icons/icon.icns"
  cp "$DESKTOP/build/icon.png" "$TAURI/icons/icon.png"
  log "copied icons"
fi

log "prepare runtime directory"
if [[ "${SKIP_RUNTIME_PREP:-0}" == "1" && -x "$RUNTIME/python/bin/python3" && -f "$RUNTIME/frontend/index.html" ]]; then
  log "skip runtime prep (SKIP_RUNTIME_PREP=1)"
else
  rm -rf "$RUNTIME"
  mkdir -p "$RUNTIME/backend" "$RUNTIME/guide" "$RUNTIME/frontend"

  log "copy backend source (no .env)"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'data' \
    --exclude '*.pyc' \
    --exclude '.env' \
    "$ROOT/backend/app" "$RUNTIME/backend/"
  cp "$ROOT/backend/requirements.txt" "$RUNTIME/backend/requirements.txt"

  log "copy guide yaml + env example"
  cp "$ROOT/guide/squads.yml" "$ROOT/guide/projects.yml" "$ROOT/guide/workspaces.yml" "$RUNTIME/guide/"
  cp "$ROOT/.env.example" "$RUNTIME/.env.example"

  log "build Next.js static export"
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
    log "ERROR: next export out/index.html missing"
    exit 1
  fi
  rsync -a --delete "$ROOT/frontend/out/" "$RUNTIME/frontend/"
  CSS_COUNT="$(find "$RUNTIME/frontend" -name '*.css' | wc -l | tr -d ' ')"
  if [[ "${CSS_COUNT:-0}" -lt 1 ]]; then
    log "ERROR: frontend CSS missing in static export"
    exit 1
  fi
  log "static pages ready css=$CSS_COUNT"

  PY_TARBALL="$DESKTOP/resources/cpython-${PYTHON_VERSION}+${PYTHON_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
  PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_TAG}/cpython-${PYTHON_VERSION}+${PYTHON_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
  if [[ ! -f "$PY_TARBALL" ]]; then
    log "download portable python $PY_URL"
    mkdir -p "$DESKTOP/resources"
    curl -L --fail --retry 3 -o "$PY_TARBALL" "$PY_URL"
  fi
  log "extract portable python"
  tar -xzf "$PY_TARBALL" -C "$RUNTIME"
  if [[ ! -x "$RUNTIME/python/bin/python3" ]]; then
    log "ERROR: python3 missing after extract"
    exit 1
  fi

  log "pip install backend requirements"
  "$RUNTIME/python/bin/python3" -m pip install --upgrade pip
  "$RUNTIME/python/bin/python3" -m pip install -r "$RUNTIME/backend/requirements.txt"
fi

if [[ -f "$RUNTIME/.env" ]]; then
  log "ERROR: runtime 含 .env，拒绝打包密钥"
  exit 1
fi

log "strip AppleDouble"
find "$DESKTOP" "$RUNTIME" -name '._*' -delete 2>/dev/null || true

BUILD_DIR="${AGENTCENTER_BUILD_DIR:-$HOME/Library/Caches/AgentCenter-desktop-build}"
mkdir -p "$BUILD_DIR"
export CARGO_TARGET_DIR="$BUILD_DIR/cargo-target"
log "tauri build output=$CARGO_TARGET_DIR"

if [[ ! -d "$DESKTOP/node_modules/@tauri-apps/cli" ]]; then
  log "npm install @tauri-apps/cli"
  (cd "$DESKTOP" && npm install --cache "$DESKTOP/.npm-cache")
fi

(cd "$DESKTOP" && npx tauri build --bundles dmg)

DMG="$(find "$CARGO_TARGET_DIR" -name 'AgentCenter_*.dmg' -o -name 'AgentCenter-*.dmg' 2>/dev/null | sort | tail -1 || true)"
if [[ -z "${DMG:-}" ]]; then
  DMG="$(ls -t "$CARGO_TARGET_DIR"/release/bundle/dmg/*.dmg 2>/dev/null | head -1 || true)"
fi
if [[ -z "${DMG:-}" ]]; then
  log "ERROR: dmg not produced"
  find "$CARGO_TARGET_DIR" -name '*.dmg' 2>/dev/null | head
  exit 1
fi

APP="$(find "$CARGO_TARGET_DIR" -type d -name 'AgentCenter.app' 2>/dev/null | head -1 || true)"
if [[ -n "${APP:-}" ]]; then
  find "$APP" -name '._*' -delete 2>/dev/null || true
  if [[ -f "$APP/Contents/Resources/runtime/.env" ]]; then
    log "ERROR: 安装包内含 .env"
    exit 1
  fi
  log "ad-hoc codesign app=$APP"
  codesign --force --deep --sign - "$APP" || log "WARN: codesign failed (may still install locally)"
fi

OUT_DIR="$ROOT/dist"
mkdir -p "$OUT_DIR"
cp "$DMG" "$OUT_DIR/"
FINAL="$OUT_DIR/$(basename "$DMG")"
log "done dmg=$FINAL size=$(du -h "$FINAL" | awk '{print $1}')"
echo "$FINAL"

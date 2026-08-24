#!/usr/bin/env bash
# 将 AgentCenter 打包为可安装的 macOS DMG。
# 日志：logs/package-dmg.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/desktop"
RUNTIME="$DESKTOP/resources/runtime"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/package-dmg.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

PYTHON_TAG="${PYTHON_STANDALONE_TAG:-20260610}"
PYTHON_VERSION="${PYTHON_STANDALONE_VERSION:-3.12.13}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$STAMP] [package-dmg] $*"; }

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *)
    log "ERROR: unsupported arch=$ARCH"
    exit 1
    ;;
esac

log "begin root=$ROOT arch=$ARCH"
cd "$ROOT"
export COPYFILE_DISABLE=1
export ELECTRON_MIRROR="${ELECTRON_MIRROR:-https://npmmirror.com/mirrors/electron/}"
export ELECTRON_BUILDER_BINARIES_MIRROR="${ELECTRON_BUILDER_BINARIES_MIRROR:-https://npmmirror.com/mirrors/electron-builder-binaries/}"
log "electron mirror=$ELECTRON_MIRROR"

if [[ ! -f "$DESKTOP/build/icon.icns" ]]; then
  log "building icns from icon.png"
  ICON_SRC="$DESKTOP/build/icon.png"
  if [[ ! -f "$ICON_SRC" ]]; then
    log "ERROR: missing $ICON_SRC"
    exit 1
  fi
  ICONSET="$DESKTOP/build/AgentCenter.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  sips -z 16 16 "$ICON_SRC" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_SRC" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_SRC" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_SRC" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_SRC" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_SRC" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_SRC" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_SRC" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$DESKTOP/build/icon.icns"
  rm -rf "$ICONSET"
  log "icon.icns ready"
fi

log "prepare runtime directory"
if [[ "${SKIP_RUNTIME_PREP:-0}" == "1" && -x "$RUNTIME/python/bin/python3" && -x "$RUNTIME/node/bin/node" && -f "$RUNTIME/frontend/server.js" ]]; then
  log "skip runtime prep (SKIP_RUNTIME_PREP=1)"
else
rm -rf "$RUNTIME"
mkdir -p "$RUNTIME/backend" "$RUNTIME/guide" "$RUNTIME/frontend"

log "copy backend source"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'data' \
  --exclude '*.pyc' \
  "$ROOT/backend/app" "$RUNTIME/backend/"
cp "$ROOT/backend/requirements.txt" "$RUNTIME/backend/requirements.txt"

log "copy guide yaml"
cp "$ROOT/guide/squads.yml" "$ROOT/guide/projects.yml" "$ROOT/guide/workspaces.yml" "$RUNTIME/guide/"
cp "$ROOT/.env.example" "$RUNTIME/.env.example"

log "build Next.js standalone"
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  (cd "$ROOT/frontend" && npm install)
fi
(cd "$ROOT/frontend" && AGENTCENTER_PACKAGING=1 NEXT_DIST_DIR=.next-pkg API_PORT=8013 npm run build)
if [[ ! -f "$ROOT/frontend/.next-pkg/standalone/server.js" ]]; then
  # Next standalone output is nested under the package directory name.
  STANDALONE_SERVER="$(find "$ROOT/frontend/.next-pkg/standalone" -name server.js | head -1)"
  if [[ -z "$STANDALONE_SERVER" ]]; then
    log "ERROR: next standalone server.js not found"
    exit 1
  fi
  STANDALONE_DIR="$(dirname "$STANDALONE_SERVER")"
else
  STANDALONE_DIR="$ROOT/frontend/.next-pkg/standalone"
fi
log "standalone dir=$STANDALONE_DIR"
rsync -a "$STANDALONE_DIR/" "$RUNTIME/frontend/"
# Next standalone 用 NEXT_DIST_DIR=.next-pkg，/_next/static 从 distDir/static 提供。
# 拷到 .next/static 会导致 CSS/JS 404，桌面端渲染成无样式 HTML。
DIST_DIR=".next-pkg"
RSF="$RUNTIME/frontend/.next-pkg/required-server-files.json"
if [[ -f "$RSF" ]]; then
  DIST_DIR="$(python3 -c "import json; print(json.load(open('$RSF'))['config'].get('distDir','.next-pkg').lstrip('./'))")"
fi
mkdir -p "$RUNTIME/frontend/$DIST_DIR"
if [[ -d "$ROOT/frontend/.next-pkg/static" ]]; then
  rsync -a "$ROOT/frontend/.next-pkg/static" "$RUNTIME/frontend/$DIST_DIR/"
  log "copied static assets dest=$RUNTIME/frontend/$DIST_DIR/static"
fi
CSS_COUNT="$(find "$RUNTIME/frontend/$DIST_DIR/static/css" -name '*.css' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${CSS_COUNT:-0}" -lt 1 ]]; then
  log "ERROR: frontend CSS missing at $DIST_DIR/static/css (UI would render unstyled)"
  exit 1
fi
if [[ -d "$ROOT/frontend/public" ]]; then
  rsync -a "$ROOT/frontend/public" "$RUNTIME/frontend/"
fi

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
  find "$RUNTIME" -maxdepth 3 -type d | head -40
  exit 1
fi

log "pip install backend requirements"
"$RUNTIME/python/bin/python3" -m pip install --upgrade pip
"$RUNTIME/python/bin/python3" -m pip install -r "$RUNTIME/backend/requirements.txt"

NODE_VERSION="${NODE_STANDALONE_VERSION:-22.18.0}"
NODE_ARCH="$ARCH"
if [[ "$ARCH" == "x86_64" ]]; then NODE_ARCH="x64"; fi
NODE_TARBALL="$DESKTOP/resources/node-v${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
if [[ ! -f "$NODE_TARBALL" ]]; then
  log "download portable node $NODE_URL"
  curl -L --fail --retry 3 -o "$NODE_TARBALL" "$NODE_URL"
fi
log "extract portable node"
tar -xzf "$NODE_TARBALL" -C "$RUNTIME"
mv "$RUNTIME/node-v${NODE_VERSION}-darwin-${NODE_ARCH}" "$RUNTIME/node"
if [[ ! -x "$RUNTIME/node/bin/node" ]]; then
  log "ERROR: node missing after extract"
  exit 1
fi
fi

log "npm install electron-builder"
(cd "$DESKTOP" && npm install --cache "$DESKTOP/.npm-cache")

log "strip AppleDouble before pack"
find "$DESKTOP/src" "$DESKTOP/resources" "$DESKTOP/build" -name '._*' -delete 2>/dev/null || true

# Build on APFS (system disk). Lexar/exFAT injects AppleDouble and breaks codesign.
BUILD_DIR="${AGENTCENTER_BUILD_DIR:-$HOME/Library/Caches/AgentCenter-desktop-build}"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

log "electron-builder dmg output=$BUILD_DIR"
(cd "$DESKTOP" && npx electron-builder --mac dmg --publish never --config.directories.output="$BUILD_DIR")

DMG="$(ls -t "$BUILD_DIR"/AgentCenter-*.dmg 2>/dev/null | head -1 || true)"
if [[ -z "$DMG" ]]; then
  log "ERROR: dmg not produced"
  ls -la "$BUILD_DIR" || true
  exit 1
fi

OUT_DIR="$ROOT/dist"
mkdir -p "$OUT_DIR"
cp "$DMG" "$OUT_DIR/"
FINAL="$OUT_DIR/$(basename "$DMG")"
log "done dmg=$FINAL size=$(du -h "$FINAL" | awk '{print $1}')"
echo "$FINAL"

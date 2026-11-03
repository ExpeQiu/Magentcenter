#!/usr/bin/env bash
# 启动服务并用系统浏览器打开（推荐方式）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_PORT="${FRONTEND_PORT:-3013}"

# 优先用 screen 持久启动
if command -v screen >/dev/null 2>&1; then
  "$ROOT/scripts/start-detached.sh"
else
  "$ROOT/scripts/start-all.sh"
  echo ""
  echo "⚠️  请勿用 Cursor 内置浏览器，请用 Safari/Chrome 打开"
  open "http://127.0.0.1:$FRONTEND_PORT" 2>/dev/null || true
fi

#!/usr/bin/env bash
# AgentCenter 一键启动（后端 + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/start.sh"
"$ROOT/scripts/start-frontend.sh"
sleep 2
"$ROOT/scripts/status.sh"

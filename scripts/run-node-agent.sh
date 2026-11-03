#!/usr/bin/env bash
# 外置 Node Agent（v2 claim-next / lease / finish）。本机 full 可与 Core 并行。
# 用法：
#   AGENTCENTER_URL=http://127.0.0.1:8013 ./scripts/run-node-agent.sh
#   FLEET_MOCK=1 ./scripts/run-node-agent.sh --once
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_SUPPORT="${HOME}/Library/Application Support/AgentCenter"
export AGENTCENTER_DATA_DIR="${AGENTCENTER_DATA_DIR:-$APP_SUPPORT/data}"
export AGENTCENTER_URL="${AGENTCENTER_URL:-http://127.0.0.1:8013}"
export PYTHONPATH="${ROOT}/fleet-edge/src:${ROOT}/node-agent/src:${PYTHONPATH:-}"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
exec python3 -m agentcenter_node.main "$@"

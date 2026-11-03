#!/usr/bin/env bash
# 独立云端执行 worker。协调器保持 DEPLOY_PROFILE=cloud 零槽。
# 用法：
#   AGENTCENTER_URL=http://云:8080 FLEET_ENROLL_TOKEN=... ./scripts/run-cloud-worker.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/fleet-edge/src:${ROOT}/cloud-worker/src:${PYTHONPATH:-}"
export FLEET_NODE_NAME="${FLEET_NODE_NAME:-cloud-worker}"
exec python3 -m agentcenter_cloud_worker "$@"

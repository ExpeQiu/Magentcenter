#!/usr/bin/env bash
# 设备侧连接器。实现在独立包 fleet-edge/，不依赖服务端代码。
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/fleet-edge.py "$@"

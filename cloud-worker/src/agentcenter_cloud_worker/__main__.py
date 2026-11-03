"""独立云端 worker 入口：复用 fleet-edge 领取循环。"""

from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s cloud-worker %(levelname)s %(message)s",
    )
    os.environ.setdefault("FLEET_NODE_NAME", "cloud-worker")
    try:
        from agentcenter_fleet.edge import main as fleet_main
    except ImportError:
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "fleet-edge" / "src"
        sys.path.insert(0, str(root))
        from agentcenter_fleet.edge import main as fleet_main

    logging.getLogger(__name__).info("cloud-worker start (coordinator stays zero-slot)")
    return int(fleet_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())

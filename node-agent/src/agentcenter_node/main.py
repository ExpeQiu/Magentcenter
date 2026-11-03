"""委托现有 fleet-edge 主循环；后续在此加租约续约与目录白名单。"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s node-agent %(levelname)s %(message)s",
    )
    try:
        from agentcenter_fleet.edge import main as fleet_main
    except ImportError:
        # 同仓开发：把 fleet-edge/src 放进 path
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "fleet-edge" / "src"
        sys.path.insert(0, str(root))
        from agentcenter_fleet.edge import main as fleet_main

    logging.getLogger(__name__).info("node-agent start via fleet-edge")
    return int(fleet_main(argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

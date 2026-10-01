#!/usr/bin/env python3
"""仓库内入口，转调独立包 agentcenter-fleet。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "fleet-edge" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentcenter_fleet.edge import main  # noqa: E402

raise SystemExit(main())

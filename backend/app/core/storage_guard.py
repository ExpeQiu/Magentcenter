"""磁盘空间不足时拒绝新任务，避免把没写上的结果报成成功。"""

from __future__ import annotations

import shutil
from pathlib import Path


class StorageError(RuntimeError):
    pass


def ensure_capacity(path: Path, min_free_mb: int = 64) -> None:
    target = path if path.is_dir() else path.parent
    target.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target)
    if usage.free < max(1, min_free_mb) * 1024 * 1024:
        raise StorageError(
            f"数据目录剩余空间不足，已停止接收新任务：{target}"
        )

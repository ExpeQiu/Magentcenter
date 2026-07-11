"""结构化日志配置。"""

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> logging.Logger:
    """配置根日志器，同时输出到控制台和文件。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path / "agentcenter.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return logging.getLogger("agentcenter")

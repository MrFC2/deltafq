"""
Logging system for DeltaFQ.

日志文件按级别分目录，按天滚动，文件名格式 yyyy-MM-dd.log：
  logs/info/       INFO 及以上（排除 ERROR/EXCEPTION）
  logs/error/      ERROR
  logs/exception/  EXCEPTION（即 ERROR + traceback）
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# 项目根目录（source/core/logger.py 往上两级）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"


class _LevelFilter(logging.Filter):
    """只允许指定级别范围内的日志通过。"""

    def __init__(self, min_level: int, max_level: int):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return self.min_level <= record.levelno <= self.max_level


class _ExceptionFilter(logging.Filter):
    """只允许带有 exc_info 的 ERROR 日志通过（即 logger.exception 调用）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR and record.exc_info is not None


class _ErrorNoExcFilter(logging.Filter):
    """只允许不带 exc_info 的 ERROR 日志通过（即 logger.error 调用）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.ERROR and record.exc_info is None


def _make_rotating_handler(subdir: str, level: int) -> logging.handlers.TimedRotatingFileHandler:
    """创建按天滚动的文件 handler，文件名为 yyyy-MM-dd.log。"""
    from datetime import date
    log_dir = _LOG_DIR / subdir
    log_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / f"{today}.log"),
        when="midnight",
        interval=1,
        backupCount=90,
        encoding="utf-8",
    )
    # 滚动时新文件命名为下一天的日期
    handler.suffix = "%Y-%m-%d.log"
    handler.namer = lambda name: str(Path(name).parent / Path(name).suffix.lstrip("."))
    handler.setLevel(level)
    return handler


def _setup_root_logger() -> None:
    """配置全局 root logger，只执行一次。"""
    root = logging.getLogger()
    if getattr(root, "_deltafq_configured", False):
        return
    root._deltafq_configured = True

    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-9s %(name)-25s >>> %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台：INFO 及以上
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件：info/ — INFO 和 WARNING（不含 ERROR）
    info_handler = _make_rotating_handler("info", logging.INFO)
    info_handler.addFilter(_LevelFilter(logging.INFO, logging.WARNING))
    info_handler.setFormatter(formatter)
    root.addHandler(info_handler)

    # 文件：error/ — ERROR（不带 traceback）
    error_handler = _make_rotating_handler("error", logging.ERROR)
    error_handler.addFilter(_ErrorNoExcFilter())
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    # 文件：exception/ — ERROR + traceback（logger.exception 调用）
    exc_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-9s %(name)-25s >>> %(message)s\n",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    exc_handler = _make_rotating_handler("exception", logging.ERROR)
    exc_handler.addFilter(_ExceptionFilter())
    exc_handler.setFormatter(exc_formatter)
    root.addHandler(exc_handler)


# 模块加载时立即配置
_setup_root_logger()


class Logger:
    """日志工具（向后兼容封装）。"""

    def __init__(self, name: str = "deltafq", level: str = "INFO"):
        self.logger = logging.getLogger(name)

    def debug(self, message: str):
        self.logger.debug(message)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def critical(self, message: str):
        self.logger.critical(message)

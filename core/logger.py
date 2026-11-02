"""带轮转的日志，并接管全局异常钩子。

所有未捕获异常（主线程与子线程）都写入 logs/app.log，便于问题回溯；
同时输出到 stderr 方便开发期观察。
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.paths import LOGS_DIR

_APP_LOG = LOGS_DIR / "app.log"
_MAX_BYTES = 2 * 1024 * 1024  # 单文件 2MB
_BACKUPS = 5                    # 保留 5 个历史文件


def get_logger(name: str = "dictation") -> logging.Logger:
    """获取（并仅初始化一次）模块级 logger。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        _APP_LOG, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


_LOG = get_logger()


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    _LOG.error(
        "未捕获异常: %s",
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    )


def _thread_excepthook(args) -> None:
    _LOG.error(
        "线程异常: %s",
        "".join(
            traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            )
        ),
    )


def install_excepthooks() -> None:
    """将全局异常与线程异常重定向到轮转日志。"""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


if __name__ == "__main__":
    _LOG.info("logger ok")

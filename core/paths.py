"""用户数据目录解析。

所有用户数据（词表、数据库、缓存、日志、配置、教材词库）统一写入
%LOCALAPPDATA%/DictationMaster，避免写入安装目录（Program Files 无写权限）
或硬编码任何用户名路径。
"""

from __future__ import annotations

import os
from pathlib import Path

# 应用名，同时作为用户数据目录名
APP_NAME = "DictationMaster"


def _app_data() -> Path:
    """解析用户数据根目录，不存在则创建。"""
    # LOCALAPPDATA 在 Windows 上指向 C:\Users\<user>\AppData\Local
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


# 各用途子目录（模块导入时即创建，保证后续读写安全）
APP_DATA = _app_data()
CONFIG_FILE = APP_DATA / "config.json"
WORDLISTS_DIR = APP_DATA / "wordlists"
DATA_DIR = APP_DATA / "data"
DB_FILE = DATA_DIR / "dictation.db"
CACHE_DIR = APP_DATA / "cache"
LOGS_DIR = APP_DATA / "logs"
TEXTBOOKS_DIR = APP_DATA / "textbooks"
ASSIGNMENTS_DIR = APP_DATA / "assignments"


def _ensure_subdirs() -> None:
    for d in (WORDLISTS_DIR, DATA_DIR, CACHE_DIR, LOGS_DIR, TEXTBOOKS_DIR,
              ASSIGNMENTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


_ensure_subdirs()

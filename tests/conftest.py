"""共享 pytest 夹具：全局 QApplication（offscreen）。

所有 UI 测试共享同一个 session 级 QApplication 单例——PySide6 不允许重复创建，
因此先复用已存在的实例。测试文件只需声明依赖 ``app`` 参数即可。
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication(sys.argv)

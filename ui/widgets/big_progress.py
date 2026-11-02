"""大字号的「3 / 20」进度显示（规范 §F3 顶部大字号序号）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ui.widgets.theme_qss import style_label


class BigProgressLabel(QLabel):
    """顶部大字号「当前 / 总数」进度标签。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("0 / 0", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(120)
        font = self.font()
        font.setPointSize(30)
        font.setBold(True)
        self.setFont(font)
        style_label(self)  # 显式主题色，避免浅色主题下继承成白字

    def set_progress(self, current: int, total: int) -> None:
        """设置当前序号与总数。"""
        self.setText(f"{current} / {total}")

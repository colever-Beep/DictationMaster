"""词卡组件：在词表页右侧以卡片方式罗列单个词条。

每张卡片展示：单词文本（主）、多音字/特殊读法 alias（副）、学科标签，以及
启用状态的色点指示。卡片高度固定、宽度由 ``AdaptiveFlowLayout`` 自动撑满每行，
从而在右栏形成整齐的卡片网格。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, FluentIcon, isDarkTheme, themeColor

from data.models import WordItem


class WordCard(CardWidget):
    """单个词条的展示卡片。"""

    def __init__(self, item: WordItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        main = QVBoxLayout(self)
        main.setContentsMargins(14, 10, 14, 10)
        main.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.word_label = QLabel(item.text, self)
        self.word_label.setObjectName("wordText")
        top.addWidget(self.word_label, 1)

        self.dot = QLabel(self)
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)

        main.addLayout(top)

        self.sub_label = QLabel(self)
        self.sub_label.setObjectName("wordSub")
        main.addWidget(self.sub_label)

        self._apply_theme()
        self._render()

    # ----------------------------------------------------------- 内容
    def _render(self) -> None:
        item = self._item
        if item.alias:
            self.sub_label.setText(item.alias)
            self.sub_label.show()
        else:
            self.sub_label.hide()
        # 启用状态色点
        if item.enabled:
            col = themeColor()
        else:
            col = QColor(150, 150, 150)
        self.dot.setStyleSheet(
            f"background-color: {col.name()}; border-radius: 5px;")

    # ----------------------------------------------------------- 主题
    def _apply_theme(self) -> None:
        dark = isDarkTheme()
        word_color = "#1A1A1A" if not dark else "#FFFFFF"
        sub_color = "#737373" if not dark else "#A6A6A6"
        self.word_label.setStyleSheet(
            f"color: {word_color}; font-size: 16px; font-weight: bold;")
        self.sub_label.setStyleSheet(f"color: {sub_color}; font-size: 12px;")
        # 禁用词整体置灰
        if not self._item.enabled:
            self.word_label.setStyleSheet(
                f"color: {sub_color}; font-size: 16px; font-weight: bold;")

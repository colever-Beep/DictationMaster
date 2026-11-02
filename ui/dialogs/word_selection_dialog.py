"""听写前单词选择对话框（规范 §F3）。

以网格复选框形式展示词表内的全部单词，支持全选 / 清空 / 反选，
确定后返回用户勾选的 WordItem 列表，用于生成本次听写的实际词表。

复选框网格被抽成独立的 ``WordCheckGrid`` 控件，便于在「布置听写任务」等
其它对话框中复用。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CheckBox, PrimaryPushButton, PushButton, SubtitleLabel

from data.models import WordItem, WordList
from ui.dialogs.base import FluentContentDialog


class WordCheckGrid(QWidget):
    """可复用的选词网格：复选框 + 全选/清空/反选 + 已选计数。"""

    # 网格列数；列数过多会导致复选框文字被截断，太少则滚动过长
    _COLUMNS = 4

    def __init__(self, wordlist: WordList, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wordlist = wordlist
        self._checks: list[tuple[CheckBox, WordItem]] = []

        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # 滚动区 + 网格
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(280)
        # qfluentwidgets 滚动区需要透明化，避免主题切换后露出黑/深灰底
        if hasattr(scroll, "enableTransparentBackground"):
            scroll.enableTransparentBackground()

        grid_widget = QWidget(scroll)
        grid = QGridLayout(grid_widget)
        grid.setSpacing(10)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setColumnStretch(self._COLUMNS, 1)  # 最后一列占满剩余宽度

        for i, item in enumerate(self._wordlist.items):
            cb = CheckBox(item.text, grid_widget)
            cb.setChecked(True)
            cb.setToolTip(item.note[:120] if item.note else "")
            cb.stateChanged.connect(self._update_count)
            self._checks.append((cb, item))
            row, col = divmod(i, self._COLUMNS)
            grid.addWidget(cb, row, col)

        scroll.setWidget(grid_widget)
        root.addWidget(scroll, 1)

        # 批量操作行
        ops = QHBoxLayout()
        ops.setSpacing(10)
        select_all = PushButton("全选", self)
        select_all.clicked.connect(self._select_all)
        clear = PushButton("清空", self)
        clear.clicked.connect(self._clear_all)
        invert = PushButton("反选", self)
        invert.clicked.connect(self._invert)
        self._count_label = BodyLabel("", self)
        ops.addWidget(select_all)
        ops.addWidget(clear)
        ops.addWidget(invert)
        ops.addStretch(1)
        ops.addWidget(self._count_label)
        root.addLayout(ops)
        self._update_count()

    def _update_count(self, _state: int = 0) -> None:
        """刷新「已选 X / 总 Y」统计。"""
        total = len(self._checks)
        selected = sum(1 for cb, _ in self._checks if cb.isChecked())
        self._count_label.setText(f"已选 {selected} / {total}")

    def _select_all(self) -> None:
        for cb, _ in self._checks:
            cb.setChecked(True)

    def _clear_all(self) -> None:
        for cb, _ in self._checks:
            cb.setChecked(False)

    def _invert(self) -> None:
        for cb, _ in self._checks:
            cb.setChecked(not cb.isChecked())

    def selected_items(self) -> list[WordItem]:
        """返回按原顺序排列的已选单词。"""
        return [item for cb, item in self._checks if cb.isChecked()]


class WordSelectionDialog(FluentContentDialog):
    """选择本次听写要包含的单词，复选框网格布局。"""

    def __init__(self, wordlist: WordList, parent: QWidget | None = None) -> None:
        super().__init__("选择听写单词", parent)
        self.setMinimumWidth(720)
        self._wordlist = wordlist

        self.viewLayout.addWidget(
            SubtitleLabel(f"{self._wordlist.name}　共 {len(self._wordlist.items)} 词", self.widget)
        )
        self._grid = WordCheckGrid(wordlist, self.widget)
        self.viewLayout.addWidget(self._grid, 1)

        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("确定", self.widget)
        ok.clicked.connect(self.accept)
        self.add_button(cancel)
        self.add_button(ok)

    def selected_items(self) -> list[WordItem]:
        """返回用户勾选的单词列表。"""
        return self._grid.selected_items()

"""历史记录页（规范 §F4 / M5）。

听写会话列表（开始时间、词表名、词数、耗时、正确率），可查看详情与删除。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PushButton,
    TableWidget,
    TitleLabel,
)

import data.database as db
from data.repository import format_duration


def _fmt_accuracy(acc) -> str:
    if acc is None:
        return "未标记"
    return f"{acc * 100:.0f}%"


class HistoryPage(QWidget):
    """历史记录：会话列表 + 详情 / 删除。"""

    def __init__(self, services: Optional[object] = None,
                 parent: object | None = None) -> None:
        super().__init__(parent)
        self.setContentsMargins(24, 24, 24, 24)
        self._services = services
        self._rows: list[dict] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(TitleLabel("历史记录", self))

        ops = QHBoxLayout()
        ops.setSpacing(12)
        self._detail_btn = PushButton("查看详情", self)
        self._detail_btn.setIcon(FluentIcon.INFO)
        self._detail_btn.clicked.connect(self._on_detail)
        self._delete_btn = PushButton("删除选中", self)
        self._delete_btn.setIcon(FluentIcon.DELETE)
        self._delete_btn.clicked.connect(self._on_delete)
        clear = PushButton("清空历史", self)
        clear.setIcon(FluentIcon.DELETE)
        clear.clicked.connect(self._on_clear)
        ops.addWidget(self._detail_btn)
        ops.addWidget(self._delete_btn)
        ops.addWidget(clear)
        ops.addStretch(1)
        refresh = PushButton("刷新", self)
        refresh.setIcon(FluentIcon.SYNC)
        refresh.clicked.connect(self.refresh)
        ops.addWidget(refresh)
        root.addLayout(ops)

        # 会话表：开始时间 | 词表 | 学科 | 词数 | 耗时 | 正确率
        self._table = TableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["开始时间", "词表", "学科", "词数", "耗时", "正确率"])
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(self._table.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        self._table.doubleClicked.connect(lambda _: self._on_detail())
        root.addWidget(self._table, 1)

    # ------------------------------------------------------------------ 数据
    def refresh(self) -> None:
        try:
            db.init_db()
            self._rows = db.list_history()
        except Exception:  # noqa: BLE001
            self._rows = []
        self._table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            texts = [
                (r.get("started_at") or "").replace("T", " "),
                r.get("wordlist_name", ""),
                "语文" if r.get("subject") == "chinese" else "英语",
                str(r.get("word_count", 0)),
                format_duration(r.get("duration_sec", 0)),
                _fmt_accuracy(r.get("accuracy")),
            ]
            for c, val in enumerate(texts):
                it = self._table.item(i, c)
                if it is None:
                    it = QTableWidgetItem(val)
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsSelectable)
                    self._table.setItem(i, c, it)
                else:
                    it.setText(val)
            # 首列挂记录 id
            first = self._table.item(i, 0)
            if first is not None:
                first.setData(Qt.ItemDataRole.UserRole + 1, r["id"])
            self._table.setRowHeight(i, 40)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------ 动作
    def _current_id(self) -> Optional[int]:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not rows:
            return None
        first = self._table.item(rows[0], 0)
        if first is None:
            return None
        return first.data(Qt.ItemDataRole.UserRole + 1)

    def _on_detail(self) -> None:
        hid = self._current_id()
        if hid is None:
            InfoBar.info("请先选择一条记录", "单击或双击任意一行。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        row = next((r for r in self._rows if r["id"] == hid), None)
        if row is None:
            return
        lines = []
        for i, d in enumerate(row.get("details") or [], start=1):
            status = d.get("status") or db.STATUS_UNSET
            lines.append(f"{i}. {d.get('text', '')}  ——  {status}")
        text = "\n".join(lines) if lines else "（无词条明细）"
        box = MessageBox(f"听写详情 · {row.get('wordlist_name', '')}",
                         f"{(row.get('started_at') or '').replace('T', ' ')}\n\n"
                         f"{text}", self.window())
        box.yesButton.setText("关闭")
        box.cancelButton.hide()
        box.exec()

    def _on_delete(self) -> None:
        hid = self._current_id()
        if hid is None:
            InfoBar.info("请先选择一条记录", "单击要删除的行。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        box = MessageBox("删除记录", "确定删除选中的这条听写记录吗？",
                         self.window())
        if not box.exec():
            return
        db.delete_history(hid)
        self.refresh()
        InfoBar.success("已删除", "记录已删除。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_clear(self) -> None:
        if not self._rows:
            return
        box = MessageBox("清空历史",
                         f"将删除全部 {len(self._rows)} 条听写记录，且不可恢复。"
                         f"确定要清空吗？", self.window())
        if not box.exec():
            return
        db.clear_history()
        self.refresh()
        InfoBar.success("已清空", "历史记录已清空。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

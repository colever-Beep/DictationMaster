"""错题本页（规范 §F4 / M5）。

全局累计写错词条，按错误次数排序；支持发起专项听写、导出 CSV、清空（二次确认）。
"""

from __future__ import annotations

import csv
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
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
    PrimaryPushButton,
    PushButton,
    TableWidget,
    TitleLabel,
)

import data.database as db
from data.models import WordItem, WordList
from data.repository import gen_id, save_wordlist


class WrongBookPage(QWidget):
    """错题本：累计写错词条列表 + 专项听写 / 导出 / 清空。"""

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

        root.addWidget(TitleLabel("错题本", self))

        # 操作条
        ops = QHBoxLayout()
        ops.setSpacing(12)
        self._practice_btn = PrimaryPushButton("专项听写", self)
        self._practice_btn.setIcon(FluentIcon.PLAY)
        self._practice_btn.clicked.connect(self._on_practice)
        self._export_btn = PushButton("导出 CSV", self)
        self._export_btn.setIcon(FluentIcon.SAVE)
        self._export_btn.clicked.connect(self._on_export)
        self._clear_btn = PushButton("清空错题本", self)
        self._clear_btn.setIcon(FluentIcon.DELETE)
        self._clear_btn.clicked.connect(self._on_clear)
        refresh = PushButton("刷新", self)
        refresh.setIcon(FluentIcon.SYNC)
        refresh.clicked.connect(self.refresh)
        ops.addWidget(self._practice_btn)
        ops.addWidget(self._export_btn)
        ops.addWidget(self._clear_btn)
        ops.addStretch(1)
        ops.addWidget(refresh)
        root.addLayout(ops)

        # 错词表：词条 | 语言 | 错误次数 | 最近写错时间
        self._table = TableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["词条", "语言", "错误次数", "最近写错时间"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(self._table.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        root.addWidget(self._table, 1)

    # ------------------------------------------------------------------ 数据
    def refresh(self) -> None:
        try:
            db.init_db()
            self._rows = db.list_wrong()
        except Exception:  # noqa: BLE001
            self._rows = []
        self._table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            texts = [
                r["text"],
                "中文" if r.get("lang") == "zh" else "英语",
                str(r["wrong_count"]),
                (r.get("last_wrong_at") or "").replace("T", " "),
            ]
            for c, val in enumerate(texts):
                it = self._table.item(i, c)
                if it is None:
                    it = QTableWidgetItem(val)
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._table.setItem(i, c, it)
                else:
                    it.setText(val)
            # 把原始数据挂在首列，供专项听写取词
            first = self._table.item(i, 0)
            first.setData(Qt.ItemDataRole.UserRole, r["text"])
            first.setData(Qt.ItemDataRole.UserRole + 1, r.get("lang", "zh"))
            self._table.setRowHeight(i, 40)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------ 动作
    def _selected_words(self) -> list[dict]:
        """选中行（未选中则取全部）对应的错词条目。"""
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            return list(self._rows)
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

    def _on_practice(self) -> None:
        """把（选中或全部）错词生成专项词表并发起听写（§F4 一键重练语义）。"""
        words = self._selected_words()
        if not words:
            InfoBar.info("错题本是空的", "先去听写几组词吧。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        wl = WordList(
            id=gen_id("wl"),
            name=f"错题专项 {datetime.now().strftime('%m-%d %H:%M')}",
            subject="chinese" if words[0].get("lang", "zh") == "zh" else "english",
            items=[WordItem(id=gen_id("it"), text=r["text"],
                            lang=r.get("lang", "zh")) for r in words],
        )
        save_wordlist(wl)
        win = self.window()
        page = getattr(win, "dictation_page", None) if win else None
        if page is not None and hasattr(page, "start_with_wordlist"):
            if hasattr(win, "switchTo"):
                win.switchTo(win.dictation_page)
            page.start_with_wordlist(wl)
        else:
            InfoBar.success("已生成专项词表",
                            f"「{wl.name}」共 {len(wl.items)} 词，请到听写页选择。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_export(self) -> None:
        if not self._rows:
            InfoBar.info("错题本是空的", "没有可导出的错词。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        default = f"错题本_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出错题本 CSV", default,
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["词条", "语言", "错误次数", "最近写错时间"])
            for r in self._rows:
                writer.writerow([r["text"],
                                 "中文" if r.get("lang") == "zh" else "英语",
                                 r["wrong_count"],
                                 (r.get("last_wrong_at") or "").replace("T", " ")])
        InfoBar.success("导出成功", path,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_clear(self) -> None:
        """清空错题本：必须 MessageBox 二次确认（规范 §3.3）。"""
        if not self._rows:
            InfoBar.info("错题本已经是空的", "", position=InfoBarPosition.TOP_RIGHT,
                         parent=self)
            return
        box = MessageBox("清空错题本",
                         f"将删除全部 {len(self._rows)} 条错词记录，且不可恢复。"
                         f"确定要清空吗？", self.window())
        if not box.exec():
            return
        db.clear_wrongbook()
        self.refresh()
        InfoBar.success("已清空", "错题本已清空。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

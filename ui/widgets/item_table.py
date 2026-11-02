"""词条表格控件：承载词表的增删改、排序、去重、打乱与单条试听按钮。

对应规范 F1.3（编辑词条）/ F1.4（单条试听）。本控件只负责「展示与交互」，
数据以 ``self.items: list[WordItem]`` 为唯一真相来源；任何改动都会重排 ``items``
并经 ``dataChanged`` 信号上抛，由编辑器刷新统计。

- 拖动排序：开启 ``InternalMove``，落点后按新顺序回写 ``items`` 再整表刷新。
- 试听：每行末尾喇叭按钮，点击只发 ``speakRequested(row)`` 信号，不在此处做 TTS，
  保持控件纯净（TTS 由上层编辑器注入服务处理）。
- 多音字别名 ``alias`` 直接作为可编辑列展示。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)
from qfluentwidgets import FluentIcon, TransparentToolButton

from data.models import WordItem
from ui.widgets.theme_qss import style_table

# 列定义
COL_IDX, COL_TEXT, COL_ALIAS, COL_ENABLED, COL_SPEAK = range(5)
_HEADERS = ["序号", "词条", "读法别名", "启用", "试听"]


class ItemTable(QTableWidget):
    """词条表格。"""

    # row 索引（与 self.items 对齐）
    speakRequested = Signal(int)
    # 数据发生任何变动（增删改/排序/去重/打乱）
    dataChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(_HEADERS), parent)
        self.items: list[WordItem] = []
        self._loading = False

        self.setHorizontalHeaderLabels(_HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(COL_IDX, 48)
        self.setColumnWidth(COL_TEXT, 220)
        self.setColumnWidth(COL_ALIAS, 200)
        self.setColumnWidth(COL_ENABLED, 56)
        self.setColumnWidth(COL_SPEAK, 56)

        self.cellChanged.connect(self._on_cell_changed)
        self.model().rowsMoved.connect(self._on_rows_moved)

        # 原生 QTableWidget 在深色主题下会回退成黑底；套 Fluent 主题样式
        style_table(self)

    # ------------------------------------------------------------------ 数据
    def set_items(self, items: list[WordItem]) -> None:
        """整体替换词条并刷新。"""
        self.items = list(items)
        self.reload()

    def get_items(self) -> list[WordItem]:
        """返回当前词条（深拷贝，避免外部修改污染内部状态）。"""
        return [WordItem(
            id=it.id, text=it.text, alias=it.alias, lang=it.lang,
            enabled=it.enabled, repeat=it.repeat, interval=it.interval, note=it.note,
        ) for it in self.items]

    def reload(self) -> None:
        """依据 ``self.items`` 重建整张表。"""
        self._loading = True
        self.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            # 序号
            idx = QTableWidgetItem(str(r + 1))
            idx.setFlags(Qt.ItemFlag.ItemIsEnabled)
            idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(r, COL_IDX, idx)

            # 词条（可编辑）
            text = QTableWidgetItem(it.text)
            text.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(r, COL_TEXT, text)

            # 别名（可编辑）
            alias = QTableWidgetItem(it.alias)
            alias.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(r, COL_ALIAS, alias)

            # 启用（勾选框）
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Checked if it.enabled else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(r, COL_ENABLED, chk)

            # 试听按钮
            btn = TransparentToolButton(FluentIcon.VOLUME, self)
            btn.setFixedSize(32, 32)
            btn.clicked.connect(lambda _checked=False, row=r: self.speakRequested.emit(row))
            self.setCellWidget(r, COL_SPEAK, btn)
        self._loading = False

    # -------------------------------------------------------------- 单元格编辑
    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._loading:
            return
        if not (0 <= row < len(self.items)):
            return
        it = self.items[row]
        if col == COL_TEXT:
            it.text = self.item(row, col).text().strip()
        elif col == COL_ALIAS:
            it.alias = self.item(row, col).text().strip()
        elif col == COL_ENABLED:
            it.enabled = self.item(row, col).checkState() == Qt.CheckState.Checked
        self.dataChanged.emit()

    # -------------------------------------------------------------- 拖动排序
    def _on_rows_moved(self, _parent, start: int, end: int, dest: int) -> None:
        if self._loading:
            return
        count = end - start + 1
        moved = self.items[start:end + 1]
        rest = self.items[:start] + self.items[end + 1:]
        insert_at = dest - count if dest > end else dest
        self.items = rest[:insert_at] + moved + rest[insert_at:]
        self.reload()
        self.dataChanged.emit()

    # -------------------------------------------------------------- 批量操作
    def add_blank(self, lang: str = "zh") -> None:
        """追加一个空词条。"""
        from data.repository import gen_id
        self.items.append(WordItem(id=gen_id("it"), text="新词条", lang=lang))
        self.reload()
        self.dataChanged.emit()

    def add_texts(self, texts: list[str], lang: str = "zh") -> int:
        """批量追加文本（自动跳过空串），返回新增条数。"""
        from data.repository import gen_id
        added = 0
        for t in texts:
            t = t.strip()
            if not t:
                continue
            self.items.append(WordItem(id=gen_id("it"), text=t, lang=lang))
            added += 1
        if added:
            self.reload()
            self.dataChanged.emit()
        return added

    def add_items(self, new_items: list[WordItem]) -> int:
        """批量追加已构造好的 WordItem（导入场景），返回新增条数。"""
        added = 0
        for it in new_items:
            if not it.text.strip():
                continue
            self.items.append(it)
            added += 1
        if added:
            self.reload()
            self.dataChanged.emit()
        return added

    def remove_selected(self) -> int:
        """删除选中行，返回删除条数。"""
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        if not rows:
            return 0
        for r in rows:
            if 0 <= r < len(self.items):
                del self.items[r]
        self.reload()
        self.dataChanged.emit()
        return len(rows)

    def move_up(self, row: int) -> None:
        """上移一行。"""
        if 0 < row < len(self.items):
            self.items[row - 1], self.items[row] = self.items[row], self.items[row - 1]
            self.reload()
            self.dataChanged.emit()

    def move_down(self, row: int) -> None:
        """下移一行。"""
        if 0 <= row < len(self.items) - 1:
            self.items[row + 1], self.items[row] = self.items[row], self.items[row + 1]
            self.reload()
            self.dataChanged.emit()

    def dedupe(self) -> int:
        """按（去空白、小写）词条去重，保留首次出现，返回移除条数。"""
        seen: set[str] = set()
        kept: list[WordItem] = []
        removed = 0
        for it in self.items:
            key = it.text.strip().lower()
            if not key or key in seen:
                removed += 1
                continue
            seen.add(key)
            kept.append(it)
        self.items = kept
        self.reload()
        self.dataChanged.emit()
        return removed

    def shuffle(self) -> None:
        """打乱顺序（仅作用于本次展示，不改存储顺序语义——此处直接改 items）。"""
        import random
        random.shuffle(self.items)
        self.reload()
        self.dataChanged.emit()

    def selected_row(self) -> int:
        """返回首个选中行，无选中返回 -1。"""
        rows = {idx.row() for idx in self.selectedIndexes()}
        return min(rows) if rows else -1

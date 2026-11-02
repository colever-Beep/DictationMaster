"""导入预览对话框（F1.2）：支持 .txt / .csv / .xlsx 解析与列选择、行勾选。

对应规范 F1.2：导入前弹预览对话框，可勾选保留哪些行、指定目标列。

依赖说明：``.xlsx`` 采用**标准库** ``zipfile`` + ``xml.etree`` 直接解析 OOXML，
不引入 ``openpyxl`` 等额外第三方库（满足规范 §1「不引入本提示词之外第三方库」约束）。
``.csv`` / ``.txt`` 用标准库 ``csv`` / 文本切分处理。
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton

from data.models import WordItem
from data.repository import gen_id
from ui.dialogs.base import FluentContentDialog
from ui.widgets.theme_qss import style_table

_MainNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col_to_idx(col: str) -> int:
    """把列字母（A/AA）转为 0 基索引。"""
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _parse_xlsx(path: Path) -> list[list[str]]:
    """用标准库解析 xlsx 首个工作表，返回二维字符串数组。"""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{_MainNS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_MainNS}t")))
        sheet = "xl/worksheets/sheet1.xml"
        if sheet not in names:
            sheet = next(n for n in names
                         if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        root = ET.fromstring(zf.read(sheet))
        rows: list[list[str]] = []
        for row in root.iter(f"{_MainNS}row"):
            cells: dict[int, str] = {}
            max_c = -1
            for c in row.findall(f"{_MainNS}c"):
                ref = c.get("r") or ""
                col = "".join(ch for ch in ref if ch.isalpha())
                ci = _col_to_idx(col) if col else 0
                t = c.get("t")
                val = ""
                v = c.find(f"{_MainNS}v")
                is_el = c.find(f"{_MainNS}is")
                if t == "s" and v is not None:
                    try:
                        val = shared[int(v.text or "0")]
                    except (ValueError, IndexError):
                        val = ""
                elif t == "inlineStr" and is_el is not None:
                    val = "".join(tt.text or "" for tt in is_el.iter(f"{_MainNS}t"))
                elif v is not None:
                    val = v.text or ""
                cells[ci] = val
                max_c = max(max_c, ci)
            rows.append([cells.get(i, "") for i in range(max_c + 1)])
    return rows


def _parse_csv(path: Path) -> list[list[str]]:
    """解析 csv：自动探测分隔符（逗号 / 制表符）。"""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    sample = text.splitlines()[0] if text else ""
    delim = "\t" if "\t" in sample else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _parse_txt(path: Path) -> list[list[str]]:
    """解析 txt：非空行逐行作为单个词条。"""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    return [[ln.strip()] for ln in text.splitlines() if ln.strip()]


def parse_file(path: str) -> list[list[str]]:
    """按扩展名分派解析，统一返回二维数组（行 × 列）。"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".xlsx":
        return _parse_xlsx(p)
    if ext == ".csv":
        return _parse_csv(p)
    return _parse_txt(p)


class ImportDialog(FluentContentDialog):
    """导入预览对话框。"""

    def __init__(self, parent, rows: list[list[str]], lang: str = "zh") -> None:
        super().__init__("导入预览", parent)
        self._rows = rows
        self._lang = lang
        self._checked: list[bool] = [True] * len(rows)
        ncols = max((len(r) for r in rows), default=1)

        # 列选择
        head = QHBoxLayout()
        head.addWidget(QLabel("词条列：", self.widget))
        self.combo_word = QComboBox(self.widget)
        for i in range(ncols):
            self.combo_word.addItem(f"第 {i + 1} 列")
        head.addWidget(self.combo_word)
        head.addSpacing(16)
        head.addWidget(QLabel("别名列：", self.widget))
        self.combo_alias = QComboBox(self.widget)
        self.combo_alias.addItem("（无）")
        for i in range(ncols):
            self.combo_alias.addItem(f"第 {i + 1} 列")
        head.addWidget(self.combo_alias)
        head.addStretch(1)
        self.viewLayout.addLayout(head)

        # 预览表
        self.table = QTableWidget(len(rows), 3, self.widget)
        self.table.setHorizontalHeaderLabels(["包含", "词条", "别名"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        style_table(self.table)  # 原生表格套 Fluent 主题样式（避免深色黑底）
        self.viewLayout.addWidget(self.table)

        # 全选 / 全不选
        sel = QHBoxLayout()
        all_btn = PushButton("全选", self.widget)
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = PushButton("全不选", self.widget)
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel.addWidget(all_btn)
        sel.addWidget(none_btn)
        sel.addStretch(1)
        self.viewLayout.addLayout(sel)

        self.combo_word.currentIndexChanged.connect(self._rebuild)
        self.combo_alias.currentIndexChanged.connect(self._rebuild)
        self._rebuild()

        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("确定导入", self.widget)
        ok.clicked.connect(self.accept)
        self.add_button(cancel)
        self.add_button(ok)

    def _set_all(self, state: bool) -> None:
        self._checked = [state] * len(self._rows)
        self._rebuild()

    def _rebuild(self) -> None:
        """按当前列选择重建预览表。"""
        word_col = self.combo_word.currentIndex()
        alias_col = self.combo_alias.currentIndex() - 1  # 0 = （无）
        self._loading = True
        for r, row in enumerate(self._rows):
            word = row[word_col] if word_col < len(row) else ""
            alias = row[alias_col] if (alias_col >= 0 and alias_col < len(row)) else ""
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Checked if self._checked[r] else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(word))
            self.table.setItem(r, 2, QTableWidgetItem(alias))
        self._loading = False

    def _collect(self) -> list[WordItem]:
        word_col = self.combo_word.currentIndex()
        alias_col = self.combo_alias.currentIndex() - 1
        out: list[WordItem] = []
        for r, row in enumerate(self._rows):
            if not self._checked[r]:
                continue
            word = row[word_col].strip() if word_col < len(row) else ""
            if not word:
                continue
            alias = ""
            if alias_col >= 0 and alias_col < len(row):
                alias = row[alias_col].strip()
            out.append(WordItem(id=gen_id("it"), text=word, alias=alias, lang=self._lang))
        return out

    @staticmethod
    def get_items(parent, path: str, lang: str = "zh") -> list[WordItem]:
        """解析文件并弹出预览；用户确认则返回词条列表，取消返回空列表。"""
        try:
            rows = parse_file(path)
        except Exception as exc:  # noqa: BLE001
            from ui.dialogs.base import msg_info
            msg_info(parent, "导入失败", f"无法解析文件：\n{exc}")
            return []
        if not rows:
            from ui.dialogs.base import msg_info
            msg_info(parent, "导入失败", "文件为空或解析结果为空。")
            return []
        dlg = ImportDialog(parent, rows, lang)
        if dlg.exec():
            return dlg._collect()
        return []

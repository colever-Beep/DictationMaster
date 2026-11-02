"""教材词库选择对话框（F1.7）：学段 → 年级 → 册 → 单元 级联选择。

对应规范 §5.1：级联选择器输出 ``(学段, 年级, 册次, 单元)``，仓库层按
``data/textbooks/*.json`` 定位并返回词条；找不到时给提示，允许用户继续手动编辑。

返回结构（经 ``get_selection`` 静态方法）：``{"name": str, "subject": str,
"words": list[str]}``；取消返回 ``None``。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout

from data.repository import (
    TextbookMeta,
    get_textbook_units,
    list_textbooks,
    load_textbook_words,
)
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton
from ui.dialogs.base import FluentContentDialog


class TextbookPickerDialog(FluentContentDialog):
    """教材级联选择器。"""

    def __init__(self, parent) -> None:
        super().__init__("从教材词库导入", parent)
        self._metas = list_textbooks()
        self._tree: dict = {}
        for m in self._metas:
            self._tree.setdefault(m.subject, {}).setdefault(m.stage, {}).setdefault(
                m.grade, {})[m.volume] = m

        if not self._metas:
            self.viewLayout.addWidget(
                QLabel("尚未发现教材词库。请在 data/textbooks/ 放置示例词库 JSON。", self.widget)
            )
            self._build_disabled()
            return

        # 级联下拉
        self.combo_subject = self._make_combo(list(self._tree.keys()))
        self.combo_stage = QComboBox(self.widget)
        self.combo_grade = QComboBox(self.widget)
        self.combo_volume = QComboBox(self.widget)
        self.combo_unit = QComboBox(self.widget)

        for label, box in (
            ("学科：", self.combo_subject),
            ("学段：", self.combo_stage),
            ("年级：", self.combo_grade),
            ("册次：", self.combo_volume),
            ("单元：", self.combo_unit),
        ):
            row = QVBoxLayout()
            row.addWidget(QLabel(label, self.widget))
            row.addWidget(box)
            self.viewLayout.addLayout(row)

        self.combo_subject.currentTextChanged.connect(self._on_subject)
        self.combo_stage.currentTextChanged.connect(self._on_stage)
        self.combo_grade.currentTextChanged.connect(self._on_grade)
        self.combo_volume.currentTextChanged.connect(self._on_volume)

        self.label_status = QLabel("", self.widget)
        self.viewLayout.addWidget(self.label_status)

        self._on_subject()
        self._refresh_ok_state()

        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("加载为词表", self.widget)
        ok.clicked.connect(self.accept)
        self.add_button(cancel)
        self.add_button(ok)
        self._ok = ok

    def _make_combo(self, items: list[str]) -> QComboBox:
        box = QComboBox(self.widget)
        box.addItems(items)
        return box

    def _build_disabled(self) -> None:
        cancel = PushButton("关闭", self.widget)
        cancel.clicked.connect(self.reject)
        self.add_button(cancel)

    # -------------------------------------------------------- 级联联动
    def _on_subject(self) -> None:
        subj = self.combo_subject.currentText()
        self.combo_stage.clear()
        self.combo_stage.addItems(list(self._tree.get(subj, {}).keys()))
        self._on_stage()

    def _on_stage(self) -> None:
        subj = self.combo_subject.currentText()
        stage = self.combo_stage.currentText()
        self.combo_grade.clear()
        self.combo_grade.addItems(list(self._tree.get(subj, {}).get(stage, {}).keys()))
        self._on_grade()

    def _on_grade(self) -> None:
        subj = self.combo_subject.currentText()
        stage = self.combo_stage.currentText()
        grade = self.combo_grade.currentText()
        self.combo_volume.clear()
        self.combo_volume.addItems(
            list(self._tree.get(subj, {}).get(stage, {}).get(grade, {}).keys())
        )
        self._on_volume()

    def _on_volume(self) -> None:
        meta = self._current_meta()
        self.combo_unit.clear()
        if meta is not None:
            self.combo_unit.addItems(get_textbook_units(meta))
        self._refresh_ok_state()

    def _current_meta(self) -> Optional[TextbookMeta]:
        subj = self.combo_subject.currentText()
        stage = self.combo_stage.currentText()
        grade = self.combo_grade.currentText()
        volume = self.combo_volume.currentText()
        return self._tree.get(subj, {}).get(stage, {}).get(grade, {}).get(volume)

    def _refresh_ok_state(self) -> None:
        meta = self._current_meta()
        ok_enabled = meta is not None and self.combo_unit.count() > 0
        if hasattr(self, "_ok"):
            self._ok.setEnabled(ok_enabled)
        if meta is not None:
            self.label_status.setText(f"已选教材：{meta.stage} {meta.grade} {meta.volume}")
        else:
            self.label_status.setText("")

    # -------------------------------------------------------- 结果
    def _result(self) -> Optional[dict]:
        meta = self._current_meta()
        if meta is None:
            return None
        unit = self.combo_unit.currentText()
        words = load_textbook_words(meta, unit)
        if not words:
            return None
        name = f"{meta.stage}{meta.grade}{meta.volume} · {unit}"
        return {"name": name, "subject": meta.subject, "words": words}

    @staticmethod
    def get_selection(parent) -> Optional[dict]:
        """打开选择对话框；确认且有效则返回选择字典，否则返回 None。"""
        dlg = TextbookPickerDialog(parent)
        if dlg.exec():
            return dlg._result()
        return None

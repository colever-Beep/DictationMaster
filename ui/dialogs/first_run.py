"""首次启动引导（规范 §F6：3 步 —— 选学科 → 建词表 → 认识报读参数）。

基于 ``FluentContentDialog``，内部用 ``QStackedWidget`` 承载 3 步；最后「完成」时
由调用方读取 ``result()`` 落的配置与词表内容。引导只在 ``cfg.first_run_done`` 为假时
出现（见 main.py），用户可随时「跳过引导」。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
)

from ui.dialogs.base import FluentContentDialog

_STEPS = ["选择学科", "建立第一份词表", "认识报读参数"]

_PARAM_NOTES = [
    ("每词朗读次数", "同一个词连续朗读几遍（低年级建议 2–3 遍）"),
    ("词间书写间隔", "朗读结束后留给孩子的书写秒数，环形倒计时会实时显示"),
    ("遍间停顿", "重复朗读时，每遍之间的安静间隔"),
    ("语速 / 音调", "相对 edge-tts 默认值的百分比与 Hz 偏移，慢一点更清晰"),
    ("音色模式", "女声 / 男声 / 男女混读（混读会在相邻词之间轮换）"),
    ("随机打乱", "打乱报读顺序，避免孩子记住位置"),
    ("纸笔模式", "屏幕全程不显示词条，听写结束后才在结果页展示答案"),
]


class FirstRunDialog(FluentContentDialog):
    """3 步首启引导对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__("欢迎使用听写助手", parent)
        self.setMinimumWidth(620)

        self._step = 0
        self._pages = QStackedWidget(self.widget)
        self.viewLayout.addWidget(SubtitleLabel("三步完成初始设置", self.widget))
        self.viewLayout.addWidget(self._pages)
        self._pages.addWidget(self._build_step_subject())
        self._pages.addWidget(self._build_step_wordlist())
        self._pages.addWidget(self._build_step_params())

        # 底部按钮：上一步 / 下一步 / 完成 / 跳过
        self._skip_btn = PushButton("跳过引导", self.widget)
        self._skip_btn.clicked.connect(self.reject)
        self._prev_btn = PushButton("上一步", self.widget)
        self._prev_btn.clicked.connect(self._on_prev)
        self._next_btn = PrimaryPushButton("下一步", self.widget)
        self._next_btn.clicked.connect(self._on_next)
        self.add_button(self._skip_btn)
        self.add_button(self._prev_btn)
        self.add_button(self._next_btn)
        self._sync_buttons()

    # ------------------------------------------------------------------ 步骤 1
    def _build_step_subject(self) -> QWidget:
        page = QWidget(self._pages)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(BodyLabel(
            "先选择默认学科。语文使用中文音色，英语使用英文音色；"
            "之后可随时在「设置」里切换。", page))
        card = CardWidget(page)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.addWidget(StrongBodyLabel("默认学科", card))
        self._subject_combo = ComboBox(card)
        self._subject_combo.addItems(["语文", "英语"])
        cl.addWidget(self._subject_combo)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ 步骤 2
    def _build_step_wordlist(self) -> QWidget:
        page = QWidget(self._pages)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(BodyLabel(
            "建立第一份词表：输入名称，每行一个词。也可以直接从内置教材导入一个单元。",
            page))

        card = CardWidget(page)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(10)
        name_row = QHBoxLayout()
        name_row.addWidget(StrongBodyLabel("词表名称", card))
        self._name_edit = LineEdit(card)
        self._name_edit.setPlaceholderText("例如：三年级上 第一单元")
        name_row.addWidget(self._name_edit, 1)
        cl.addLayout(name_row)

        self._words_edit = TextEdit(card)
        self._words_edit.setPlaceholderText("每行一个词（可留空，稍后再建）")
        self._words_edit.setMinimumHeight(150)
        cl.addWidget(self._words_edit)

        import_row = QHBoxLayout()
        import_row.addStretch(1)
        tbtn = PushButton("从内置教材导入", card)
        tbtn.setIcon(FluentIcon.LIBRARY)
        tbtn.clicked.connect(self._on_import_textbook)
        import_row.addWidget(tbtn)
        cl.addLayout(import_row)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ 步骤 3
    def _build_step_params(self) -> QWidget:
        page = QWidget(self._pages)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(BodyLabel(
            "听写页的「报读参数」决定了怎么读、间隔多久。先了解这几项就够了：", page))
        card = CardWidget(page)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(8)
        for name, desc in _PARAM_NOTES:
            row = QHBoxLayout()
            row.addWidget(StrongBodyLabel(name, card))
            cl.addLayout(row)
            cl.addWidget(CaptionLabel(desc, card))
        lay.addWidget(card)

        tip = CardWidget(page)
        tl = QVBoxLayout(tip)
        tl.setContentsMargins(16, 12, 16, 12)
        tl.addWidget(StrongBodyLabel("快捷键", tip))
        tl.addWidget(CaptionLabel(
            "Space 开始 / 暂停 · ← → 上/下一个词 · R 重读本题 · Esc 停止", tip))
        lay.addWidget(tip)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ 交互
    def _on_prev(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._pages.setCurrentIndex(self._step)
            self._sync_buttons()

    def _on_next(self) -> None:
        if self._step < len(_STEPS) - 1:
            self._step += 1
            self._pages.setCurrentIndex(self._step)
            self._sync_buttons()
        else:
            self.accept()

    def _sync_buttons(self) -> None:
        self._prev_btn.setEnabled(self._step > 0)
        last = self._step == len(_STEPS) - 1
        self._next_btn.setText("完成" if last else "下一步")
        self._next_btn.setIcon(FluentIcon.ACCEPT if last else FluentIcon.RIGHT_ARROW)

    def _on_import_textbook(self) -> None:
        from ui.dialogs.textbook_picker import TextbookPickerDialog

        sel = TextbookPickerDialog.get_selection(self)
        if not sel:
            return
        self._name_edit.setText(sel["name"])
        self._words_edit.setPlainText("\n".join(sel["words"]))
        # 教材带学科，同步到第一步的选择
        idx = 0 if sel.get("subject") == "chinese" else 1
        self._subject_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------ 结果
    def result(self) -> dict:
        """返回引导结果：学科 / 词表名 / 词条列表。"""
        words = [w.strip() for w in self._words_edit.toPlainText().splitlines()]
        words = [w for w in words if w]
        return {
            "subject": "chinese" if self._subject_combo.currentIndex() == 0
            else "english",
            "wordlist_name": self._name_edit.text().strip(),
            "words": words,
        }

    @staticmethod
    def ask(parent=None) -> Optional[dict]:
        """弹出引导；完成返回结果字典，跳过返回 None。"""
        dlg = FirstRunDialog(parent)
        if dlg.exec():
            return dlg.result()
        return None

"""词表编辑器对话框（F1.1/F1.3/F1.4）：增删改词条、排序、去重、打乱、单条试听、导入。

对应规范 §5.1 词表编辑：
- 新建 / 编辑复用同一对话框；``wordlist=None`` 视为新建。
- 工具栏支持：添加词条、从文件导入（txt/csv/xlsx 预览）、从教材词库导入、
  去重、打乱、上移、下移、删除选中。
- 单条试听：点击表格右侧喇叭，经 ``Services`` 走 edge-tts 合成并播放；
  未注入 Services 时禁用试听并提示。
- 顶部显示词表名称（可改）与学科（语文/英语），底部显示词数与预计时长（F1.8）。

保存即写盘（``save_wordlist``）；取消不落盘。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)

from app_config import cfg
from core.services import Services
from data.models import WordItem, WordList
from data.repository import estimate_seconds, format_duration, gen_id, save_wordlist
from ui.dialogs.base import FluentContentDialog
from ui.dialogs.import_dialog import ImportDialog
from ui.dialogs.textbook_picker import TextbookPickerDialog
from ui.widgets.item_table import ItemTable


class WordListEditorDialog(FluentContentDialog):
    """词表编辑器。"""

    def __init__(self, parent, services: Optional[Services],
                 wordlist: Optional[WordList] = None) -> None:
        super().__init__("编辑词表" if wordlist else "新建词表", parent)
        self._services = services
        if wordlist is None:
            self._wl = WordList(id=gen_id("wl"), name="未命名词表",
                                subject=cfg.subject.value, items=[])
            self._is_new = True
        else:
            # 复制一份，编辑过程中不影响传入对象
            # 保留 builtin / grade，避免编辑内置词表时丢失「内置/年级」属性
            self._wl = WordList(
                id=wordlist.id, name=wordlist.name, subject=wordlist.subject,
                items=[WordItem(
                    id=it.id, text=it.text, alias=it.alias, lang=it.lang,
                    enabled=it.enabled, repeat=it.repeat, interval=it.interval,
                    note=it.note) for it in wordlist.items],
                created_at=wordlist.created_at, updated_at=wordlist.updated_at,
                builtin=wordlist.builtin, grade=wordlist.grade,
            )
            self._is_new = False
        self._pending_rid: Optional[str] = None

        self._build_top()
        self._build_toolbar()
        self._build_table()
        self._build_footer()

        # 单条试听信号（仅连接一次；对话销毁时 Qt 自动断开与 self 的连接）
        if services is not None:
            services.tts.single_ready.connect(self._on_speak_ready)
            services.tts.single_failed.connect(self._on_speak_failed)

        self._refresh_stats()

    # ----------------------------------------------------------- 构建 UI
    def _build_top(self) -> None:
        top = QHBoxLayout()
        top.addWidget(SubtitleLabel("名称：", self.widget))
        self.name_edit = QLineEdit(self.widget)
        self.name_edit.setText(self._wl.name)
        self.name_edit.setClearButtonEnabled(True)
        top.addWidget(self.name_edit, 1)

        top.addSpacing(16)
        top.addWidget(SubtitleLabel("学科：", self.widget))
        self.subject_combo = QComboBox(self.widget)
        self.subject_combo.addItem("语文", "chinese")
        self.subject_combo.addItem("英语", "english")
        idx = self.subject_combo.findData(self._wl.subject)
        self.subject_combo.setCurrentIndex(max(idx, 0))
        self.subject_combo.currentIndexChanged.connect(self._on_subject_changed)
        top.addWidget(self.subject_combo)
        self.viewLayout.addLayout(top)

        self.stats_label = QLabel("", self.widget)
        self.stats_label.setObjectName("statsLabel")
        self.viewLayout.addWidget(self.stats_label)

    def _build_toolbar(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        def btn(icon, tip, slot) -> ToolButton:
            b = TransparentToolButton(icon, self.widget)
            b.setToolTip(tip)
            b.setFixedSize(34, 34)
            b.clicked.connect(slot)
            return b

        bar.addWidget(btn(FluentIcon.ADD, "添加词条", self._add_blank))
        bar.addWidget(btn(FluentIcon.DOWNLOAD, "从文件导入", self._import_file))
        bar.addWidget(btn(FluentIcon.LIBRARY, "从教材词库导入", self._import_textbook))
        bar.addWidget(btn(FluentIcon.FILTER, "去重", self._dedupe))
        bar.addWidget(btn(FluentIcon.ROTATE, "打乱顺序", self._shuffle))
        bar.addWidget(btn(FluentIcon.UP, "上移", self._move_up))
        bar.addWidget(btn(FluentIcon.DOWN, "下移", self._move_down))
        bar.addWidget(btn(FluentIcon.DELETE, "删除选中", self._remove_selected))
        bar.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.viewLayout.addLayout(bar)

    def _build_table(self) -> None:
        self._table = ItemTable(self.widget)
        self._table.set_items(self._wl.items)
        self._table.dataChanged.connect(self._refresh_stats)
        self._table.speakRequested.connect(self._on_speak)
        self.viewLayout.addWidget(self._table, 1)

    def _build_footer(self) -> None:
        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("保存", self.widget)
        ok.clicked.connect(self._on_save)
        self.add_button(cancel)
        self.add_button(ok)

    # ----------------------------------------------------------- 交互
    def _on_subject_changed(self, _index: int) -> None:
        self._wl.subject = self.subject_combo.currentData()

    def _lang(self) -> str:
        return "en" if self._wl.subject == "english" else "zh"

    def _add_blank(self) -> None:
        self._table.add_blank(self._lang())

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择词表文件", "", "文本或表格 (*.txt *.csv *.xlsx)")
        if not path:
            return
        items = ImportDialog.get_items(self, path, self._lang())
        if items:
            added = self._table.add_items(items)
            InfoBar.success("导入完成", f"已添加 {added} 个词条",
                            parent=self, position=InfoBarPosition.TOP)

    def _import_textbook(self) -> None:
        sel = TextbookPickerDialog.get_selection(self)
        if not sel:
            return
        lang = "en" if sel["subject"] == "english" else "zh"
        added = self._table.add_texts(sel["words"], lang)
        # 学科跟随教材
        idx = self.subject_combo.findData(sel["subject"])
        if idx >= 0:
            self.subject_combo.setCurrentIndex(idx)
        if added:
            InfoBar.success("导入完成", f"从教材导入 {added} 个词条",
                            parent=self, position=InfoBarPosition.TOP)

    def _dedupe(self) -> None:
        removed = self._table.dedupe()
        if removed:
            InfoBar.info("已去重", f"移除 {removed} 个重复词条",
                         parent=self, position=InfoBarPosition.TOP)

    def _shuffle(self) -> None:
        self._table.shuffle()

    def _move_up(self) -> None:
        row = self._table.selected_row()
        if row > 0:
            self._table.move_up(row)

    def _move_down(self) -> None:
        row = self._table.selected_row()
        if row >= 0:
            self._table.move_down(row)

    def _remove_selected(self) -> None:
        removed = self._table.remove_selected()
        if removed:
            self._refresh_stats()

    # ----------------------------------------------------------- 单条试听
    def _on_speak(self, row: int) -> None:
        if self._services is None:
            InfoBar.warning("不可用", "语音服务未初始化", parent=self)
            return
        if not (0 <= row < len(self._table.items)):
            return
        it = self._table.items[row]
        if not it.text.strip():
            return
        voice = (cfg.default_voice_en.value if it.lang == "en"
                 else cfg.default_voice_zh.value)
        self._pending_rid = f"editor_{id(self)}_{row}"
        self._services.tts.synthesize(
            self._pending_rid, it.text, voice,
            cfg.rate.value, cfg.volume.value, cfg.pitch.value)

    def _on_speak_ready(self, rid: str, path: str) -> None:
        if rid != self._pending_rid or self._services is None:
            return
        self._pending_rid = None
        self._services.player.play_file(path)

    def _on_speak_failed(self, rid: str, err: str) -> None:
        if rid != self._pending_rid:
            return
        self._pending_rid = None
        InfoBar.error("试听失败", str(err), parent=self,
                      position=InfoBarPosition.TOP)

    # ----------------------------------------------------------- 统计 / 保存
    def _refresh_stats(self) -> None:
        items = self._table.get_items()
        enabled = [i for i in items if i.enabled]
        tmp = WordList(id="", name="", subject=self._wl.subject, items=items)
        secs = estimate_seconds(tmp, cfg.repeat.value,
                                cfg.interval.value, cfg.inner_pause.value)
        self.stats_label.setText(
            f"共 {len(items)} 词（启用 {len(enabled)}） · 预计 {format_duration(secs)}")

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            InfoBar.warning("请填写名称", "词表名称不能为空", parent=self)
            return
        items = self._table.get_items()
        if not items:
            InfoBar.warning("词表为空", "请至少添加一个词条", parent=self)
            return
        self._wl.name = name
        self._wl.items = items
        save_wordlist(self._wl)
        super().accept()

    @staticmethod
    def edit(parent, services: Optional[Services],
             wordlist: Optional[WordList] = None) -> Optional[WordList]:
        """打开编辑器；保存成功返回最新 WordList（已从编辑器落盘），取消返回 None。"""
        dlg = WordListEditorDialog(parent, services, wordlist)
        if dlg.exec():
            return dlg._wl
        return None

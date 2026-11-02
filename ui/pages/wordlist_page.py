"""我的词表页（M3 词表管理实现，抽屉化导航 + 卡片罗列）。

布局：
- 左侧：可折叠「词表子导航抽屉」``WordListDrawer``，按
  「自建词表 / 默认教材词表 → 小学·初中·高中」分组罗列所有词表；顶部按钮可
  在展开(显示名称+学科·词数)与收起(仅图标)之间平滑切换（抽屉化）。
- 右侧：选中词表后，以 ``AdaptiveFlowLayout`` 卡片网格罗列其全部词条
  （单词 + 多音字/特殊读法 + 启用状态色点），并提供操作工具栏。

对应规范 §5.1 F1.1–F1.8：操作新建/导入/重命名/复制/删除/导出/编辑均保留。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    AdaptiveFlowLayout,
    BodyLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
)

from app_config import cfg
from core.services import Services
from data.models import WordList
from data.repository import (
    copy_wordlist,
    delete_wordlist,
    estimate_seconds,
    export_wordlist,
    format_duration,
    gen_id,
    list_wordlists,
    rename_wordlist,
)
from ui.dialogs.base import msg_confirm
from ui.dialogs.import_dialog import ImportDialog
from ui.dialogs.wordlist_editor import WordListEditorDialog
from ui.pages.base import PageBase
from ui.widgets.theme_qss import style_label
from ui.widgets.word_card import WordCard
from ui.widgets.wordlist_drawer import WordListDrawer


class WordListPage(PageBase):
    """我的词表页。"""

    def __init__(self, services: Optional[Services] = None, parent: QWidget | None = None) -> None:
        super().__init__("我的词表", parent)
        self._services = services
        self._all: list[WordList] = []
        self._current: Optional[WordList] = None
        self._build_toolbar()
        self._build_split()
        self._reload()

    # ----------------------------------------------------------- 工具栏
    def _build_toolbar(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        new_btn = PrimaryPushButton(FluentIcon.ADD, "新建词表", self)
        new_btn.clicked.connect(self._on_new)
        bar.addWidget(new_btn)

        import_btn = PushButton(FluentIcon.DOWNLOAD, "从文件导入", self)
        import_btn.clicked.connect(self._on_import_file)
        bar.addWidget(import_btn)

        refresh_btn = PushButton(FluentIcon.SYNC, "刷新", self)
        refresh_btn.clicked.connect(self._reload)
        bar.addWidget(refresh_btn)

        bar.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("搜索词表名称…")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self._on_search)
        bar.addWidget(self.search_box)

        self.body.addLayout(bar)

    # ----------------------------------------------------------- 主体（抽屉 + 卡片区）
    def _build_split(self) -> None:
        split = QHBoxLayout()
        split.setSpacing(12)

        # 左：词表子导航抽屉（可折叠）
        self.drawer = WordListDrawer(self)
        self.drawer.selected.connect(self._on_drawer_select)
        split.addWidget(self.drawer, 0)

        # 右：词表概要 + 词卡网格
        right = QVBoxLayout()
        right.setSpacing(10)

        self.detail_title = SubtitleLabel("未选择词表", self)
        style_label(self.detail_title)
        right.addWidget(self.detail_title)

        self.detail_meta = BodyLabel("", self)
        style_label(self.detail_meta)
        right.addWidget(self.detail_meta)

        # 操作工具栏
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_edit = PushButton(FluentIcon.EDIT, "打开编辑", self)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_rename = PushButton(FluentIcon.EDIT, "重命名", self)
        self.btn_rename.clicked.connect(self._on_rename)
        self.btn_copy = PushButton(FluentIcon.COPY, "复制副本", self)
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_delete = PushButton(FluentIcon.DELETE, "删除", self)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_export = PushButton(FluentIcon.SAVE_AS, "导出", self)
        self.btn_export.clicked.connect(self._on_export)
        for b in (self.btn_edit, self.btn_rename, self.btn_copy,
                  self.btn_delete, self.btn_export):
            actions.addWidget(b)
        actions.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        right.addLayout(actions)

        # 词卡网格
        self.card_scroll = ScrollArea(self)
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_scroll.enableTransparentBackground()
        self.card_container = QWidget(self.card_scroll)
        self.card_layout = AdaptiveFlowLayout(self.card_container, needAni=False)
        self.card_layout.setVerticalSpacing(12)
        self.card_layout.setHorizontalSpacing(12)
        self.card_layout.setContentsMargins(4, 4, 4, 4)
        self.card_layout.setWidgetMinimumWidth(200)
        self.card_container.setLayout(self.card_layout)
        self.card_scroll.setWidget(self.card_container)
        right.addWidget(self.card_scroll, 1)

        split.addLayout(right, 1)
        self.body.addLayout(split, 1)
        self._set_detail_enabled(False)

    # ----------------------------------------------------------- 数据
    _GRADES = ["小学", "初中", "高中"]

    def _reload(self) -> None:
        self._all = list_wordlists()
        self._rebuild_drawer()
        # 选中保持：优先保留上次选中的词表
        sel = self.drawer.selected_id()
        if sel and any(w.id == sel for w in self._all):
            self._on_drawer_select(sel)
        else:
            first = next((w for w in self._all), None)
            if first is not None:
                self.drawer.select(first.id)
            else:
                self._clear_detail()

    def _rebuild_drawer(self) -> None:
        kw = self.search_box.text().strip().lower()
        user_wls = [w for w in self._all
                    if not w.builtin and (not kw or kw in w.name.lower())]
        builtin_wls = [w for w in self._all
                       if w.builtin and (not kw or kw in w.name.lower())]
        by_grade = {g: [] for g in self._GRADES}
        orphan = []
        for wl in builtin_wls:
            if wl.grade in by_grade:
                by_grade[wl.grade].append(wl)
            else:
                orphan.append(wl)
        # 分组顺序：自建词表 → 默认教材 · 小学/初中/高中（其它内置兜底）
        groups: list[tuple[str, list[WordList]]] = [("自建词表", user_wls)]
        for g in self._GRADES:
            groups.append((f"默认教材 · {g}", by_grade[g]))
        if orphan:
            groups.append(("其它内置", orphan))
        self._drawer_groups = groups
        self.drawer.set_wordlists(groups)

    def _on_search(self, _text: str) -> None:
        self._rebuild_drawer()

    # ----------------------------------------------------------- 选择 / 渲染
    def _on_drawer_select(self, wid: str) -> None:
        wl = next((w for w in self._all if w.id == wid), None)
        if wl is None:
            self._clear_detail()
            return
        self._current = wl
        self._set_detail_enabled(True)
        subj = "英语" if wl.subject == "english" else "语文"
        kind = "内置 · " + (wl.grade or "教材") if wl.builtin else "自建"
        enabled = sum(1 for i in wl.items if i.enabled)
        secs = estimate_seconds(wl, cfg.repeat.value,
                               cfg.interval.value, cfg.inner_pause.value)
        self.detail_title.setText(wl.name)
        self.detail_meta.setText(
            f"类型：{kind}　学科：{subj}　词数：{len(wl.items)}（启用 {enabled}）　"
            f"预计：{format_duration(secs)}")
        self._render_cards(wl)

    def _render_cards(self, wl: WordList) -> None:
        self._clear_cards()
        if not wl.items:
            empty = BodyLabel("该词表暂无词条，点击「打开编辑」添加。", self.card_container)
            style_label(empty)
            self.card_layout.addWidget(empty)
            return
        for item in wl.items:
            self.card_layout.addWidget(WordCard(item, self.card_container))

    def _clear_cards(self) -> None:
        while self.card_layout.count():
            widget = self.card_layout.takeAt(0)
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _clear_detail(self) -> None:
        self._current = None
        self._set_detail_enabled(False)
        self.detail_title.setText("未选择词表")
        self.detail_meta.setText("")
        self._clear_cards()

    def _set_detail_enabled(self, enabled: bool) -> None:
        for b in (self.btn_edit, self.btn_rename, self.btn_copy,
                  self.btn_delete, self.btn_export):
            b.setEnabled(enabled)

    def _current_wl(self) -> Optional[WordList]:
        return self._current

    # ----------------------------------------------------------- 操作
    def _on_new(self) -> None:
        wl = WordList(id=gen_id("wl"), name="未命名词表",
                      subject=cfg.subject.value, items=[])
        result = WordListEditorDialog.edit(self, self._services, wl)
        if result is not None:
            InfoBar.success("已保存", f"词表「{result.name}」已创建",
                            parent=self, position=InfoBarPosition.TOP)
            self._reload()

    def _on_edit(self) -> None:
        wl = self._current_wl()
        if wl is None:
            return
        result = WordListEditorDialog.edit(self, self._services, wl)
        if result is not None:
            InfoBar.success("已保存", f"词表「{result.name}」已更新",
                            parent=self, position=InfoBarPosition.TOP)
            self._reload()

    def _on_rename(self) -> None:
        wl = self._current_wl()
        if wl is None:
            return
        from ui.dialogs.base import TextInputDialog
        dlg = TextInputDialog("重命名词表", "新名称：", wl.name, self)
        if dlg.exec():
            new_name = dlg.text_value()
            if new_name and new_name != wl.name:
                rename_wordlist(wl.id, new_name)
                self._reload()

    def _on_copy(self) -> None:
        wl = self._current_wl()
        if wl is None:
            return
        new = copy_wordlist(wl.id)
        if new is not None:
            InfoBar.success("已复制", f"已生成副本「{new.name}」",
                            parent=self, position=InfoBarPosition.TOP)
            self._reload()

    def _on_delete(self) -> None:
        wl = self._current_wl()
        if wl is None:
            return
        if msg_confirm(self, "删除词表",
                       f"确定删除「{wl.name}」吗？此操作不可撤销。"):
            delete_wordlist(wl.id)
            InfoBar.info("已删除", f"词表「{wl.name}」已删除",
                         parent=self, position=InfoBarPosition.TOP)
            self._current = None
            self._reload()

    def _on_export(self) -> None:
        wl = self._current_wl()
        if wl is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出词表", f"{wl.name}.txt",
            "文本 (*.txt);;CSV (*.csv)")
        if not path:
            return
        fmt = export_wordlist(wl, path)
        InfoBar.success("已导出", f"已导出为 {fmt.upper()}：{Path(path).name}",
                        parent=self, position=InfoBarPosition.TOP)

    def _on_import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择词表文件", "", "文本或表格 (*.txt *.csv *.xlsx)")
        if not path:
            return
        lang = "en" if cfg.subject.value == "english" else "zh"
        items = ImportDialog.get_items(self, path, lang)
        if not items:
            return
        wl = WordList(id=gen_id("wl"), name=Path(path).stem,
                      subject=cfg.subject.value, items=items)
        result = WordListEditorDialog.edit(self, self._services, wl)
        if result is not None:
            InfoBar.success("已保存", f"词表「{result.name}」已创建",
                            parent=self, position=InfoBarPosition.TOP)
            self._reload()

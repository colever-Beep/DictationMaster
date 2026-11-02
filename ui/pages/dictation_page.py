"""听写主页：状态机 + 参数面板 + 结果页（规范 §F3 / M4）。

页面由三个视图组成，通过 ``QStackedWidget`` 切换：
- 设置视图：选择词表 + 报读参数卡片（``ParamCard``）+ 开始按钮；
- 播放视图：大字号序号、环形倒计时、当前词条（纸笔模式隐藏）、控制条；
- 结果视图：听写完成汇总 + 答案册（结束后显示答案）。

页面只负责把引擎信号映射到控件，不实现任何听写逻辑（逻辑在 ``core.dictation_engine``）。
"""

from __future__ import annotations

import csv
from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    TableWidget,
    TitleLabel,
)

import data.database as db
from core.dictation_engine import DictationEngine, EngineState, PlayConfig
from data.models import WordItem, WordList
from data.repository import gen_id, get_wordlist, list_wordlists, save_wordlist
from data.assignments_repo import (
    delete_assignment,
    list_assignments,
    mark_done,
    pending_assignments,
    upsert_assignment_dict,
)
from core.github_sync import make_github_sync
from ui.dialogs.assignment_dialog import AssignmentCreateDialog, AssignmentManageDialog
from ui.dialogs.word_selection_dialog import WordSelectionDialog
from ui.dialogs.pre_dictation_dialog import PreDictationDialog
from ui.widgets.github_worker import GitHubTaskWorker
from ui.widgets.big_progress import BigProgressLabel
from ui.widgets.countdown_ring import CountdownRing
from ui.widgets.param_card import ParamCard
from ui.widgets.theme_qss import style_label, style_page


class DictationPage(QWidget):
    """听写播放主页（M4 状态机驱动）。"""

    def __init__(self, services: Optional[object] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setContentsMargins(24, 24, 24, 24)
        style_page(self)  # 页面根容器套主题背景，杜绝子控件透明透出黑底
        self._services = services

        self._engine: Optional[DictationEngine] = None
        self._state = EngineState.IDLE
        self._countdown_n = 0
        self._current_item = None
        self._cur_idx = 0
        self._paper_mode = True
        self._show_answer = True
        self._last_wordlist: Optional[WordList] = None
        self._last_cfg = None
        self._last_result: Optional[dict] = None
        self._session_started_at: Optional[datetime] = None
        self._history_id: Optional[int] = None
        self._marks_applied = False
        self._replay_connected = False
        self._active_assignment = None  # 当前会话若来自某份布置，记录之（完成后标记 done）

        if services is not None:
            self._engine = DictationEngine(
                services.tts, services.player, services.fallback)
            self._connect_engine()

        self._setup_ui()
        self._setup_shortcuts()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(TitleLabel("听写", self))

        self._stack = QStackedWidget(self)
        self._setup_view = self._build_setup_view()
        self._play_view = self._build_play_view()
        self._result_view = self._build_result_view()
        self._stack.addWidget(self._setup_view)
        self._stack.addWidget(self._play_view)
        self._stack.addWidget(self._result_view)
        root.addWidget(self._stack, 1)

    def _build_setup_view(self) -> QWidget:
        area = ScrollArea(self)
        container = QWidget(area)
        vbox = QVBoxLayout(container)
        vbox.setSpacing(16)
        vbox.setContentsMargins(0, 0, 12, 0)

        # 待听写任务（课代表入口）：教师备课时布置，次日一键执行
        pending_card = CardWidget(container)
        pc = QVBoxLayout(pending_card)
        pc.setContentsMargins(16, 16, 16, 16)
        pc.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("待听写任务", pending_card))
        head.addStretch(1)
        manage_btn = PushButton("管理布置", pending_card)
        manage_btn.setIcon(FluentIcon.SETTING)
        manage_btn.clicked.connect(self._open_manage)
        head.addWidget(manage_btn)
        pull_btn = PushButton("从 GitHub 拉取", pending_card)
        pull_btn.setIcon(FluentIcon.DOWNLOAD)
        pull_btn.clicked.connect(self._on_pull_github)
        head.addWidget(pull_btn)
        pc.addLayout(head)
        self._assign_list = QWidget(pending_card)
        self._assign_list_layout = QVBoxLayout(self._assign_list)
        self._assign_list_layout.setContentsMargins(0, 0, 0, 0)
        self._assign_list_layout.setSpacing(8)
        pc.addWidget(self._assign_list)
        vbox.addWidget(pending_card)
        self._refresh_assignments()

        # 词表选择
        pick_card = CardWidget(container)
        pick = QVBoxLayout(pick_card)
        pick.setContentsMargins(16, 16, 16, 16)
        pick.setSpacing(10)
        pick.addWidget(StrongBodyLabel("选择词表", pick_card))

        row = QHBoxLayout()
        self._wordlist_combo = ComboBox(pick_card)
        self._refresh_wordlists()
        refresh = PushButton("刷新", pick_card)
        refresh.setIcon(FluentIcon.SYNC)
        refresh.clicked.connect(self._refresh_wordlists)
        row.addWidget(self._wordlist_combo, 1)
        row.addWidget(refresh)
        pick.addLayout(row)
        vbox.addWidget(pick_card)

        # 参数卡片
        self._param_card = ParamCard(container)
        vbox.addWidget(self._param_card)

        # 开始 / 布置 按钮
        start_card = CardWidget(container)
        sc = QVBoxLayout(start_card)
        sc.setContentsMargins(16, 16, 16, 16)
        sc.setSpacing(10)
        start = PrimaryPushButton("开始听写", start_card)
        start.setIcon(FluentIcon.PLAY)
        start.clicked.connect(self._on_start)
        sc.addWidget(start)

        assign_row = QHBoxLayout()
        assign_row.setSpacing(8)
        assign_btn = PushButton("布置听写任务", start_card)
        assign_btn.setIcon(FluentIcon.SEND)
        assign_btn.clicked.connect(self._on_assign_create)
        assign_row.addWidget(assign_btn)
        assign_row.addStretch(1)
        sc.addLayout(assign_row)
        vbox.addWidget(start_card)

        vbox.addStretch(1)
        area.setWidget(container)
        area.setWidgetResizable(True)
        # 原生 QScrollArea 视口在浅/深色主题下会回退成深灰/黑底，需透明化
        area.enableTransparentBackground()
        return area

    def _build_play_view(self) -> QWidget:
        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setSpacing(16)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 顶部：序号 + 环形倒计时
        top_card = CardWidget(container)
        top = QHBoxLayout(top_card)
        top.setContentsMargins(20, 16, 20, 16)
        top.setSpacing(24)
        self._big = BigProgressLabel(top_card)
        top.addWidget(self._big)
        top.addStretch(1)
        self._ring = CountdownRing(top_card)
        top.addWidget(self._ring)
        vbox.addWidget(top_card)

        # 中部：当前词 / 倒计时数字
        mid_card = CardWidget(container)
        mid = QVBoxLayout(mid_card)
        mid.setContentsMargins(20, 28, 20, 28)
        self._center = QLabel("", mid_card)
        self._center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._center.font()
        font.setPointSize(34)
        font.setBold(True)
        self._center.setFont(font)
        style_label(self._center)  # 显式主题色，避免浅色主题下继承成白字
        mid.addWidget(self._center)
        vbox.addWidget(mid_card)

        # 状态条
        self._status = BodyLabel("", container)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(self._status)

        # 控制条
        ctrl_card = CardWidget(container)
        ctrl = QHBoxLayout(ctrl_card)
        ctrl.setContentsMargins(16, 12, 16, 12)
        ctrl.setSpacing(12)
        ctrl.addStretch(1)

        self._pause_btn = PrimaryPushButton("暂停", ctrl_card)
        self._pause_btn.setIcon(FluentIcon.PAUSE)
        self._pause_btn.clicked.connect(self._on_pause_resume)
        self._prev_btn = PushButton("上一个", ctrl_card)
        self._prev_btn.clicked.connect(lambda: self._engine and self._engine.prev())
        self._replay_btn = PushButton("重读本题", ctrl_card)
        self._replay_btn.setIcon(FluentIcon.ROTATE)
        self._replay_btn.clicked.connect(lambda: self._engine and self._engine.replay_current())
        self._skip_btn = PushButton("跳过", ctrl_card)
        self._skip_btn.clicked.connect(lambda: self._engine and self._engine.next())
        self._stop_btn = PushButton("停止", ctrl_card)
        self._stop_btn.setIcon(FluentIcon.CLOSE)
        self._stop_btn.clicked.connect(self._on_stop)

        for b in (self._pause_btn, self._prev_btn, self._replay_btn,
                  self._skip_btn, self._stop_btn):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        vbox.addWidget(ctrl_card)

        vbox.addStretch(1)
        return container

    def _build_result_view(self) -> QWidget:
        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setSpacing(16)
        vbox.setContentsMargins(0, 0, 0, 0)

        card = CardWidget(container)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(12)

        cl.addWidget(TitleLabel("听写完成", card))
        self._result_label = BodyLabel("", card)
        cl.addWidget(self._result_label)

        # 结果表：序号 | 词条 | 状态（单击行重听该词，§F4）
        self._result_table = TableWidget(card)
        self._result_table.setColumnCount(3)
        self._result_table.setHorizontalHeaderLabels(["序号", "词条", "状态"])
        self._result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._result_table.verticalHeader().setVisible(False)
        self._result_table.setEditTriggers(
            self._result_table.EditTrigger.NoEditTriggers)
        self._result_table.setSelectionBehavior(
            self._result_table.SelectionBehavior.SelectRows)
        self._result_table.setMinimumHeight(280)
        self._result_table.cellClicked.connect(self._on_result_row_clicked)
        cl.addWidget(self._result_table, 1)

        # 批量操作行
        ops = QHBoxLayout()
        ops.setSpacing(12)
        mark_all = PushButton("全部标记已掌握", card)
        mark_all.setIcon(FluentIcon.ACCEPT)
        mark_all.clicked.connect(self._on_mark_all_mastered)
        retrain = PrimaryPushButton("一键重练错词", card)
        retrain.setIcon(FluentIcon.ROTATE)
        retrain.clicked.connect(self._on_retrain_wrong)
        export = PushButton("导出 CSV", card)
        export.setIcon(FluentIcon.SAVE)
        export.clicked.connect(self._on_export_csv)
        ops.addWidget(mark_all)
        ops.addWidget(retrain)
        ops.addWidget(export)
        ops.addStretch(1)
        again = PushButton("再来一次", card)
        again.setIcon(FluentIcon.PLAY)
        again.clicked.connect(self._on_restart)
        back = PushButton("返回", card)
        back.clicked.connect(self._on_leave_result)
        ops.addWidget(again)
        ops.addWidget(back)
        cl.addLayout(ops)

        vbox.addWidget(card, 1)
        return container

    # ------------------------------------------------------------------ 引擎连接
    def _connect_engine(self) -> None:
        e = self._engine
        e.state_changed.connect(self._on_state)
        e.progress_changed.connect(self._on_progress)
        e.preparing_progress.connect(
            lambda d, t: self._status.setText(f"正在准备语音 {d}/{t}…"))
        e.countdown_tick.connect(self._on_countdown)
        e.writing_tick.connect(self._on_writing)
        e.word_changed.connect(self._on_word)
        e.word_repeat_changed.connect(self._on_repeat)
        e.fallback_saying.connect(
            lambda it, idx: self._status.setText(f"离线引擎播报：{it.text}"))
        e.finished.connect(self._on_finished)
        e.info.connect(self._on_info)

    # ------------------------------------------------------------------ 信号处理
    def _on_state(self, new, _old) -> None:
        self._state = new
        self._update_pause_btn(new)
        self._update_controls(new)
        if new == EngineState.IDLE:
            self._stack.setCurrentWidget(self._setup_view)
            self._refresh_assignments()
        elif new == EngineState.FINISHED:
            self._stack.setCurrentWidget(self._result_view)

    def _on_progress(self, cur: int, total: int) -> None:
        self._cur_idx = cur
        self._big.set_progress(cur, total)

    def _on_countdown(self, n: int) -> None:
        self._countdown_n = n
        if n > 0:
            self._center.setText(str(n))
            self._ring.set_value(n, 3)
            self._status.setText(f"准备开始：{n}")
        else:
            self._ring.clear()
            self._center.setText("")

    def _on_writing(self, rem: float, total: float) -> None:
        self._ring.set_value(rem, total)
        self._status.setText(f"书写中：剩余 {rem:.0f} 秒")
        self._update_center()

    def _on_word(self, item, idx: int) -> None:
        self._current_item = item
        self._update_center()

    def _on_repeat(self, k: int, total: int) -> None:
        self._status.setText(f"正在播放：第 {self._cur_idx} 词（第 {k}/{total} 遍）")

    def _on_finished(self, result: dict) -> None:
        self._last_result = result
        self._fill_result(result)

    def _on_info(self, msg: str) -> None:
        InfoBar.warning("提示", msg, position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ------------------------------------------------------------------ 视图辅助
    def _update_center(self) -> None:
        if self._state == EngineState.COUNTDOWN:
            self._center.setText(str(self._countdown_n) if self._countdown_n > 0 else "")
            return
        if self._state in (EngineState.SPEAKING, EngineState.INNER_GAP,
                           EngineState.WRITING):
            if self._paper_mode:
                self._center.setText("听写中…（纸笔模式已隐藏词语）")
            elif self._current_item is not None:
                self._center.setText(self._current_item.text)
            else:
                self._center.setText("")
        elif self._state == EngineState.PAUSED:
            self._center.setText("已暂停")
        else:
            self._center.setText("")

    def _update_pause_btn(self, state: EngineState) -> None:
        if state == EngineState.PAUSED:
            self._pause_btn.setText("继续")
            self._pause_btn.setIcon(FluentIcon.PLAY)
        else:
            self._pause_btn.setText("暂停")
            self._pause_btn.setIcon(FluentIcon.PAUSE)

    def _update_controls(self, state: EngineState) -> None:
        active = state in (
            EngineState.PREPARING, EngineState.COUNTDOWN, EngineState.SPEAKING,
            EngineState.INNER_GAP, EngineState.WRITING, EngineState.PAUSED,
        )
        for b in (self._pause_btn, self._prev_btn, self._replay_btn,
                  self._skip_btn, self._stop_btn):
            b.setEnabled(active)

    # ------------------------------------------------------------------ 动作
    def _refresh_wordlists(self) -> None:
        self._wordlist_combo.clear()
        self._wordlists = list_wordlists()
        if not self._wordlists:
            self._wordlist_combo.addItem("（暂无词表，请先在「我的词表」创建）")
            return
        for wl in self._wordlists:
            tag = f"〔{wl.grade}·内置〕" if wl.builtin else "〔自建〕"
            self._wordlist_combo.addItem(f"{wl.name} {tag}")

    def _get_selected_wordlist(self) -> Optional[WordList]:
        if not getattr(self, "_wordlists", None):
            return None
        idx = self._wordlist_combo.currentIndex()
        if idx < 0 or idx >= len(self._wordlists):
            return None
        return self._wordlists[idx]

    def _on_start(self) -> None:
        if self._engine is None:
            return
        wl = self._get_selected_wordlist()
        if wl is None:
            InfoBar.warning("无法开始", "请先创建一个词表并在上方选择。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        if not wl.items:
            InfoBar.warning("词表为空", "当前词表没有单词，请先添加。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return

        dlg = WordSelectionDialog(wl, self)
        if not dlg.exec():
            return
        selected = dlg.selected_items()
        if not selected:
            InfoBar.warning("未选择单词", "请至少选择一个单词开始听写。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return

        filtered = WordList(
            id=wl.id,
            name=wl.name,
            subject=wl.subject,
            items=selected,
            created_at=wl.created_at,
            updated_at=wl.updated_at,
        )
        self._begin_session(filtered, self._param_card.build_config(wl.subject))

    # ------------------------------------------------------------------ 布置任务（教师备课）
    def _on_assign_create(self) -> None:
        """教师：把当前所选词表 + 当前参数布置成一份待听写任务。"""
        wl = self._get_selected_wordlist()
        if wl is None:
            InfoBar.warning("无法布置", "请先在上方选择一个词表。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        if not wl.items:
            InfoBar.warning("词表为空", "当前词表没有单词，无法布置。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        cfg = self._param_card.build_config(wl.subject)
        dlg = AssignmentCreateDialog(wl, cfg, self)
        if dlg.exec():
            asg = dlg.result_assignment
            InfoBar.success("已布置", f"「{asg.name}」已保存，截止 {asg.due_date}。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            self._refresh_assignments()

    def _open_manage(self) -> None:
        """打开布置管理对话框（查看 / 删除 / 重置 / GitHub 拉取）。"""
        dlg = AssignmentManageDialog(self)
        dlg.exec()
        self._refresh_assignments()

    def _on_pull_github(self) -> None:
        """教室端：从 GitHub 一键拉取听写任务（按 id 去重）。"""
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning("未配置 GitHub", "请先在「设置 → GitHub 同步」填写仓库与 Token。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.info("正在拉取…", "正在从 GitHub 拉取听写任务。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        worker = GitHubTaskWorker(lambda: self._do_pull_github(sync), self)
        worker.done.connect(self._on_pull_github_done)
        worker.attach(self).start()

    def _do_pull_github(self, sync) -> dict:
        remotes = sync.pull_tasks()
        local_ids = {a.id for a in list_assignments()}
        added = skipped = 0
        for d in remotes:
            if d.get("id") in local_ids:
                skipped += 1
                continue
            upsert_assignment_dict(d)
            added += 1
        return {"added": added, "skipped": skipped, "total": len(remotes)}

    def _on_pull_github_done(self, ok: bool, payload) -> None:
        if not ok:
            InfoBar.error("拉取失败", f"{payload}",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.success(
            "已同步", f"新增 {payload['added']} 个任务，跳过已存在 {payload['skipped']} 个"
            f"（远端共 {payload['total']} 个）。",
            position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._refresh_assignments()

    def _refresh_assignments(self) -> None:
        """重建「待听写任务」列表（课代表入口）。"""
        if not hasattr(self, "_assign_list_layout"):
            return
        while self._assign_list_layout.count():
            item = self._assign_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        pending = pending_assignments()
        if not pending:
            hint = BodyLabel(
                "今日暂无待听写任务。教师可在下方点「布置听写任务」，"
                "次日课代表即可在此一键听写。", self._assign_list)
            self._assign_list_layout.addWidget(hint)
            return
        for a in pending:
            self._assign_list_layout.addWidget(self._build_assign_row(a))

    def _build_assign_row(self, a: "DictationAssignment") -> QWidget:
        """生成单条待听写任务的卡片行。"""
        row = CardWidget(self._assign_list)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(StrongBodyLabel(a.name, row))
        n = len(a.selected_ids) if a.selected_ids else "全部"
        subj = "英语" if a.subject == "english" else "语文"
        info.addWidget(CaptionLabel(
            f"{subj} · 词表：{a.wordlist_name} · 范围：{n} 词 · 截止：{a.due_date}", row))
        rl.addLayout(info, 1)

        go = PrimaryPushButton("开始听写", row)
        go.setIcon(FluentIcon.PLAY)
        go.clicked.connect(lambda _checked=False, asg=a: self._on_start_assignment(asg))
        rl.addWidget(go)
        del_btn = PushButton(FluentIcon.DELETE, "", row)
        del_btn.setToolTip("删除该布置")
        del_btn.clicked.connect(
            lambda _checked=False, asg=a: self._on_delete_assignment(asg))
        rl.addWidget(del_btn)
        return row

    def _on_start_assignment(self, a: "DictationAssignment") -> None:
        """课代表：按教师布置直接开始听写（无需再选词）。

        优先使用布置中自包含的单词数据（跨机导入场景，教室电脑可能无原词表）；
        仅当无 words 数据时回退到本地词表查找。
        """
        if self._engine is None:
            return

        if a.words:
            items = [WordItem(
                id=w.get("id") or gen_id("it"),
                text=w.get("text", ""),
                alias=w.get("alias", ""),
                lang=w.get("lang", "zh"),
                note=w.get("note", ""),
            ) for w in a.words]
        else:
            wl = get_wordlist(a.wordlist_id)
            if wl is None:
                InfoBar.warning("词表缺失", f"布置「{a.name}」的来源词表已被删除，无法执行。",
                                position=InfoBarPosition.TOP_RIGHT, parent=self)
                return
            if a.selected_ids:
                idset = set(a.selected_ids)
                items = [it for it in wl.items if it.id in idset]
            else:
                items = list(wl.items)

        if not items:
            InfoBar.warning("无可用单词", "该布置没有可听写的单词，请重新布置或删除。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        subject = a.subject or (items[0].lang == "en" and "english" or "chinese")
        filtered = WordList(
            id=a.wordlist_id or gen_id("wl"),
            name=a.wordlist_name or "听写",
            subject=subject,
            items=items,
        )
        try:
            cfg = PlayConfig(**a.config)
        except TypeError:
            cfg = self._param_card.build_config(subject)
        self._active_assignment = a
        self._begin_session(filtered, cfg)

    def _on_delete_assignment(self, a: "DictationAssignment") -> None:
        delete_assignment(a.id)
        InfoBar.info("已删除", f"布置「{a.name}」已删除。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._refresh_assignments()

    def _begin_session(self, wl: WordList, cfg) -> None:
        """以给定词表与配置开启一次听写（含「错题专项听写」入口）。

        正式开始前的「听前信息确认」弹窗在此弹出：用户确认后才切到播放视图并
        ``engine.start()``；取消则退回当前页面、不启动本轮听写。
        """
        if self._engine is None:
            return

        dlg = PreDictationDialog(wl, cfg, self)
        if not dlg.exec():
            return

        self._last_wordlist = wl
        self._last_cfg = cfg
        self._paper_mode = cfg.paper_mode
        self._show_answer = cfg.show_answer_at_end
        self._session_started_at = datetime.now()
        self._history_id: Optional[int] = None
        self._marks_applied = False
        self._current_item = None
        self._center.setText("")
        self._ring.clear()
        self._status.setText("准备中…")
        self._stack.setCurrentWidget(self._play_view)
        self._engine.start(wl, cfg)

    def _on_pause_resume(self) -> None:
        if self._engine is None:
            return
        if self._state == EngineState.PAUSED:
            self._engine.resume()
        else:
            self._engine.pause()

    def _on_stop(self) -> None:
        if self._engine is None:
            return
        self._engine.stop()

    def _on_restart(self) -> None:
        if self._engine is None or self._last_wordlist is None or self._last_cfg is None:
            self._stack.setCurrentWidget(self._setup_view)
            return
        self._apply_marks_and_save()      # 先结算上一次会话
        self._begin_session(self._last_wordlist, self._last_cfg)

    # ------------------------------------------------------------------ 结果与复盘（M5）
    def _collect_marks(self) -> list[dict[str, Any]]:
        """从结果表收集每词状态：[{text, alias, lang, status}, ...]。"""
        details: list[dict[str, Any]] = []
        for r in range(self._result_table.rowCount()):
            combo = self._result_table.cellWidget(r, 2)
            status = combo.currentText() if combo else db.STATUS_UNSET
            details.append({
                "text": self._result_table.item(r, 1).data(Qt.ItemDataRole.UserRole) or "",
                "alias": self._result_table.item(r, 1).data(Qt.ItemDataRole.ToolTipRole) or "",
                "lang": self._result_table.item(r, 1).data(Qt.ItemDataRole.UserRole + 1) or "zh",
                "status": status,
            })
        return details

    def _apply_marks_and_save(self) -> None:
        """离开结果页前结算：错题/掌握落库 + 回写历史正确率与明细。"""
        if self._marks_applied or not self._last_result:
            return
        self._marks_applied = True
        details = self._collect_marks()
        stats = db.apply_result_marks(details)
        marked = [d for d in details if d["status"] != db.STATUS_UNSET]
        accuracy = None
        if marked:
            ok = sum(1 for d in marked if d["status"] == db.STATUS_OK)
            accuracy = ok / len(details) if details else None
        if self._history_id:
            db.update_history_result(self._history_id, accuracy, details)
        if stats["wrong"]:
            InfoBar.success("已记入错题本", f"{stats['wrong']} 个错词已累计。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_leave_result(self) -> None:
        self._apply_marks_and_save()
        self._stack.setCurrentWidget(self._setup_view)
        self._refresh_wordlists()

    def _on_finished(self, result: dict) -> None:
        self._last_result = result
        # 若本次会话来自某份教师布置，标记其已完成（不再出现在待听写列表）
        if self._active_assignment is not None:
            mark_done(self._active_assignment.id)
            self._active_assignment = None
            self._refresh_assignments()
        # 立即落一条历史（正确率待用户标记后回写）
        started = getattr(self, "_session_started_at", None) or datetime.now()
        duration = (datetime.now() - started).total_seconds()
        try:
            self._history_id = db.add_history(
                started.isoformat(timespec="seconds"),
                self._last_wordlist.name if self._last_wordlist else "（未知词表）",
                result.get("subject", ""),
                result.get("total", 0),
                duration,
                result.get("words", []),
            )
        except Exception:  # noqa: BLE001  落库失败不阻断结果展示
            self._history_id = None
        self._fill_result(result)

    def _fill_result(self, result: dict) -> None:
        total = result.get("total", 0)
        subj = "语文" if result.get("subject") == "chinese" else "英语"
        self._result_label.setText(
            f"本次听写共 {total} 词（{subj}）。单击行可重听该词；"
            f"在「状态」列标记写错 / 已掌握后返回，将计入错题本。")
        words = result.get("words", [])
        self._result_table.setRowCount(len(words))
        for i, w in enumerate(words):
            idx_item = QTableWidgetItem(str(i + 1))
            text = w.get("text", "")
            alias = w.get("alias", "")
            display = text + (f"（读法：{alias}）" if alias else "")
            text_item = QTableWidgetItem(display)
            # 用数据角色保存原始 text / lang，供结算与重练使用
            text_item.setData(Qt.ItemDataRole.UserRole, text)
            text_item.setData(Qt.ItemDataRole.ToolTipRole, alias)
            text_item.setData(Qt.ItemDataRole.UserRole + 1, w.get("lang", "zh"))
            self._result_table.setItem(i, 0, idx_item)
            self._result_table.setItem(i, 1, text_item)
            combo = ComboBox(self._result_table)
            combo.addItems([db.STATUS_UNSET, db.STATUS_WRONG, db.STATUS_OK])
            self._result_table.setCellWidget(i, 2, combo)
            self._result_table.setRowHeight(i, 44)

    def _on_result_row_clicked(self, row: int, _col: int) -> None:
        """单击结果行 → 重听该词（走 TTS 服务，缓存命中则秒开）。"""
        if self._services is None:
            return
        item = self._result_table.item(row, 1)
        if item is None:
            return
        text = item.data(Qt.ItemDataRole.UserRole) or item.text()
        lang = item.data(Qt.ItemDataRole.UserRole + 1) or "zh"
        cfg = self._last_cfg
        voice = cfg.voices[0] if cfg and cfg.voices else (
            "zh-CN-XiaoxiaoNeural" if lang == "zh" else "en-US-AriaNeural")
        rate = cfg.rate if cfg else "-10%"
        vol = cfg.volume if cfg else "+0%"
        pitch = cfg.pitch if cfg else "+0Hz"
        rid = f"replay-{row}"
        # 已连接则复用（同一信号多次连接会重复播放）
        if not getattr(self, "_replay_connected", False):
            self._services.tts.single_ready.connect(
                lambda r, path: self._services.player.play_file(path)
                if r.startswith("replay-") else None)
            self._services.tts.single_failed.connect(
                lambda r, e: InfoBar.warning("重听失败", str(e),
                                             position=InfoBarPosition.TOP_RIGHT,
                                             parent=self)
                if r.startswith("replay-") else None)
            self._replay_connected = True
        self._services.tts.synthesize(rid, text, voice, rate, vol, pitch)

    def _on_mark_all_mastered(self) -> None:
        for r in range(self._result_table.rowCount()):
            combo = self._result_table.cellWidget(r, 2)
            if combo:
                combo.setCurrentText(db.STATUS_OK)

    def _on_retrain_wrong(self) -> None:
        """一键重练错词：把标记为「写错」的词生成新词表并直接开始听写。"""
        self._apply_marks_and_save()
        wrong = [d for d in self._collect_marks() if d["status"] == db.STATUS_WRONG]
        if not wrong:
            InfoBar.info("没有错词", "请先把写错的词标记为「写错」。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        wl = WordList(
            id=gen_id("wl"),
            name=f"错词重练 {datetime.now().strftime('%m-%d %H:%M')}",
            subject=self._last_result.get("subject", "chinese") if self._last_result
            else "chinese",
            items=[],
        )
        from data.models import WordItem
        wl.items = [WordItem(id=gen_id("it"), text=d["text"], alias=d.get("alias", ""),
                             lang=d.get("lang", "zh")) for d in wrong]
        save_wordlist(wl)
        self._refresh_wordlists()
        InfoBar.success("已生成错词词表",
                        f"「{wl.name}」共 {len(wl.items)} 词，开始专项听写。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._begin_session(wl, self._last_cfg)

    def _on_export_csv(self) -> None:
        """结果表导出 CSV（UTF-8 BOM，Excel 可直接打开，§F4）。"""
        if not self._last_result:
            return
        default = f"听写结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出结果 CSV", default,
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        details = self._collect_marks()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["序号", "词条", "读法", "语言", "状态"])
            for i, d in enumerate(details, start=1):
                writer.writerow([i, d["text"], d.get("alias", ""),
                                 "中文" if d.get("lang") == "zh" else "英语",
                                 d.get("status", db.STATUS_UNSET)])
        InfoBar.success("导出成功", path,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ------------------------------------------------------------------ 快捷键
    def _setup_shortcuts(self) -> None:
        if self._engine is None:
            return

        def bind(key, fn):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)

        def active():
            return self._engine.is_active() or self._state == EngineState.PAUSED

        bind("Space", lambda: self._on_pause_resume() if active() else None)
        bind("Left", lambda: self._engine.prev() if active() else None)
        bind("Right", lambda: self._engine.next() if active() else None)
        bind("R", lambda: self._engine.replay_current() if active() else None)
        bind("Escape", lambda: self._engine.stop() if active() else None)

    # ------------------------------------------------------------------ 供主窗口调用
    def refresh_wordlists(self) -> None:
        """供外部（首启引导完成、其它页面新建词表后）刷新下拉列表。"""
        self._refresh_wordlists()

    def start_with_wordlist(self, wl: WordList) -> None:
        """由其它页面（如错题本「专项听写」）发起的一次听写。"""
        if self._engine is None:
            return
        self._refresh_wordlists()
        self._begin_session(wl, self._param_card.build_config(wl.subject))

    def is_session_active(self) -> bool:
        """是否正在听写（用于退出 / 切换页面二次确认）。"""
        return self._engine is not None and self._engine.is_active()

    def stop_session(self) -> None:
        """停止当前听写会话并回到设置视图。"""
        if self._engine is not None:
            self._engine.stop()

    # ------------------------------------------------------------------ 线程收尾
    def closeEvent(self, event) -> None:  # noqa: D401
        """页面销毁前等待 GitHub 同步线程结束，避免 QThread 被提前回收。"""
        for w in list(getattr(self, "_gh_workers", []) or []):
            try:
                w.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._gh_workers = []
        super().closeEvent(event)

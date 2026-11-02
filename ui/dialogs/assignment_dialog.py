"""听写布置 / 管理对话框（教师「备课布置」需求）。

- ``AssignmentCreateDialog``：教师选择词表内要听写的单词 + 设定截止日期，把「范围 + 参数」
  保存为一份布置任务，次日课代表一键执行。
- ``AssignmentManageDialog``：查看 / 删除全部布置，或把已完成的重置回待办。

两者均继承自 ``FluentContentDialog``，可直接 ``exec()``。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from data.models import DictationAssignment, WordList
from data.assignments_repo import (
    assignment_to_dict,
    delete_assignment,
    export_assignment_file,
    import_assignment_file,
    list_assignments,
    reset_done,
    save_assignment,
    upsert_assignment_dict,
)
from data.repository import gen_id
from core.github_sync import make_github_sync
from ui.dialogs.base import FluentContentDialog
from ui.dialogs.word_selection_dialog import WordCheckGrid
from ui.widgets.github_worker import GitHubTaskWorker


def _default_due() -> QDate:
    """默认截止日期：次日。"""
    return QDate.currentDate().addDays(1)


def _report_upload_result(host, ok: bool, payload, name: str) -> None:
    """统一处理上传结果提示（含「保留远端同名任务」的跳过分支）。"""
    if not ok:
        InfoBar.error("上传失败", "请检查仓库 / Token 与网络后重试。",
                      duration=6000,
                      position=InfoBarPosition.TOP_RIGHT, parent=host)
        return
    if isinstance(payload, dict) and payload.get("skipped"):
        InfoBar.warning(
            "已跳过", f"仓库中已存在「{name}」，按设置未覆盖（可在设置页改回覆盖）。",
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT, parent=host)
        return
    InfoBar.success("已上传", f"「{name}」已上传到 GitHub，教室端可拉取。",
                    position=InfoBarPosition.TOP_RIGHT, parent=host)


def _config_summary(cfg: dict) -> str:
    """把 PlayConfig（dict）渲染成一目了然的中文摘要。"""
    subject = "英语" if cfg.get("subject") == "english" else "语文"
    order = "随机打乱" if cfg.get("shuffle") else "顺序"
    paper = "开启" if cfg.get("paper_mode") else "关闭"
    answer = "显示" if cfg.get("show_answer_at_end") else "不显示"
    beeps = []
    if cfg.get("countdown_beep"):
        beeps.append("倒计时")
    if cfg.get("word_beep"):
        beeps.append("每词")
    if cfg.get("end_beep"):
        beeps.append("结束")
    beep_txt = "、".join(beeps) if beeps else "无"
    return (
        f"学科：{subject}\n"
        f"每词朗读 {cfg.get('repeat', 2)} 遍 · 词间间隔 {cfg.get('interval', 10)} 秒 · "
        f"遍间停顿 {cfg.get('inner_pause', 1.5)} 秒\n"
        f"语速 {cfg.get('rate', '-10%')} · 音量 {cfg.get('volume', '+0%')} · "
        f"音调 {cfg.get('pitch', '+0Hz')}\n"
        f"报读顺序：{order} · 纸笔模式：{paper} · 结束显示答案：{answer} · 提示音：{beep_txt}"
    )


class AssignmentCreateDialog(FluentContentDialog):
    """教师布置听写任务：选词 + 命名 + 截止日期，保存为一份布置。"""

    def __init__(self, wordlist: WordList, config, parent: QWidget | None = None) -> None:
        super().__init__("布置听写任务", parent)
        self.setMinimumWidth(760)
        self._wordlist = wordlist
        # 归一化：调用方可能传入 PlayConfig（dataclass）或普通 dict
        if isinstance(config, dict):
            self._config = dict(config)
        else:
            self._config = dict(getattr(config, "__dict__", {}))
        self.result_assignment: Optional[DictationAssignment] = None

        due = _default_due()
        self._build_content(due)
        self._add_buttons()

    def _build_content(self, due: QDate) -> None:
        wl = self._wordlist
        self.viewLayout.addWidget(
            SubtitleLabel(f"{wl.name}　共 {len(wl.items)} 词", self.widget)
        )

        # 选词网格
        self._grid = WordCheckGrid(wl, self.widget)
        self.viewLayout.addWidget(self._grid, 1)

        # 参数摘要（取自听写页当前设定；如需微调请返回听写页调整后再布置）
        card = CardWidget(self.widget)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(6)
        cl.addWidget(CaptionLabel("本次报读参数（沿用听写页当前设置）", card))
        summary = BodyLabel(_config_summary(self._config), card)
        summary.setWordWrap(True)
        cl.addWidget(summary)
        self.viewLayout.addWidget(card)

        # 命名 + 截止日期
        meta = QHBoxLayout()
        meta.setSpacing(12)
        name_lbl = BodyLabel("任务名称", self.widget)
        self._name_edit = QLineEdit(self.widget)
        self._name_edit.setText(f"{due.month()}月{due.day()}日 听写 · {wl.name}")
        due_lbl = BodyLabel("截止日期（课代表在此日前需完成）", self.widget)
        self._due_edit = QDateEdit(self.widget)
        self._due_edit.setCalendarPopup(True)
        self._due_edit.setDate(due)
        self._due_edit.setMinimumDate(QDate.currentDate())
        meta.addWidget(name_lbl)
        meta.addWidget(self._name_edit, 1)
        meta.addWidget(due_lbl)
        meta.addWidget(self._due_edit)
        self.viewLayout.addLayout(meta)

    def _add_buttons(self) -> None:
        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        # 导出文件：把当前所选范围导出为自包含布置文件，供其它电脑（课代表）导入
        export = PushButton(FluentIcon.SAVE_AS, "导出文件", self.widget)
        export.clicked.connect(self._on_export)
        # 上传到 GitHub：把布置推送到仓库，教室端可一键拉取
        upload = PushButton(FluentIcon.UP, "上传到 GitHub", self.widget)
        upload.clicked.connect(self._on_upload)
        ok = PrimaryPushButton("布置", self.widget)
        ok.setIcon(FluentIcon.SEND)
        ok.clicked.connect(self._on_ok)
        self.add_button(cancel)
        self.add_button(export)
        self.add_button(upload)
        self.add_button(ok)

    def _on_upload(self) -> None:
        """把当前所选范围保存为布置并推送到 GitHub（本地也会留存一份）。"""
        asg = self._build_assignment()
        if asg is None:
            return
        save_assignment(asg)
        self.result_assignment = asg
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning(
                "未配置 GitHub", "请先在「设置 → GitHub 同步」填写仓库与 Token；"
                "任务已保存在本机。", position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.info("正在上传…", f"正在把「{asg.name}」推送到 GitHub。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        name = asg.name
        overwrite = bool(cfg.github_upload_overwrite.value)
        payload = assignment_to_dict(asg)
        worker = GitHubTaskWorker(
            lambda: sync.push_task(payload, overwrite=overwrite), self)
        worker.done.connect(
            lambda ok, res, n=name, h=self: _report_upload_result(h, ok, res, n))
        worker.attach(self).start()

    def _on_ok(self) -> None:
        asg = self._build_assignment()
        if asg is None:
            return
        save_assignment(asg)
        self.result_assignment = asg
        # 宿主页面在弹窗关闭后仍存活，自动上传线程登记到页面上，避免 QThread 被回收
        host = self.parent() or self
        self.accept()
        self._auto_upload(asg, host)

    def _auto_upload(self, asg: DictationAssignment, host) -> None:
        """布置后自动上传（受「设置 → 上传默认设置 → 布置后自动上传」控制）。"""
        if not cfg.github_auto_upload.value:
            return
        sync = make_github_sync()
        if sync is None:
            return
        name = asg.name
        overwrite = bool(cfg.github_upload_overwrite.value)
        payload = assignment_to_dict(asg)
        worker = GitHubTaskWorker(
            lambda: sync.push_task(payload, overwrite=overwrite), host)
        worker.done.connect(
            lambda ok, res, n=name, h=host: _report_upload_result(h, ok, res, n))
        worker.attach(host).start()

    def _build_assignment(self) -> Optional[DictationAssignment]:
        """按当前对话框内容构造一份（尚未落盘的）布置对象。"""
        selected = self._grid.selected_items()
        if not selected:
            InfoBar.warning("未选择单词", "请至少选择一个单词作为听写范围。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return None
        name = self._name_edit.text().strip() or f"{self._wordlist.name} 听写"
        due = self._due_edit.date().toString("yyyy-MM-dd")
        # 自包含：把所选单词数据一并写入，导入方无需依赖原词表
        words = [{
            "id": it.id, "text": it.text, "alias": it.alias,
            "lang": it.lang, "note": it.note,
        } for it in selected]
        return DictationAssignment(
            id=gen_id("asg"),
            name=name,
            wordlist_id=self._wordlist.id,
            wordlist_name=self._wordlist.name,
            subject=self._wordlist.subject,
            selected_ids=[it.id for it in selected],
            words=words,
            config=dict(self._config),
            due_date=due,
        )

    def _on_export(self) -> None:
        asg = self._build_assignment()
        if asg is None:
            return
        default = f"{asg.name}.dictation-task.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出布置文件", default,
            "布置文件 (*.dictation-task.json)")
        if not path:
            return
        export_assignment_file(asg, path)
        InfoBar.success("已导出", f"布置文件已保存到：{path}",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)


class AssignmentManageDialog(FluentContentDialog):
    """管理全部布置：查看、删除、把已完成的重置回待办。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("管理听写布置", parent)
        self.setMinimumWidth(640)
        self._build_content()

    def _build_content(self) -> None:
        from data.assignments_repo import list_assignments

        assignments = list_assignments()
        if not assignments:
            self.viewLayout.addWidget(BodyLabel("暂无布置任务。", self.widget))
            self._add_sync_buttons()
            close = PushButton("关闭", self.widget)
            close.clicked.connect(self.accept)
            self.add_button(close)
            return

        scroll = QScrollArea(self.widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(scroll.horizontalScrollBarPolicy())
        if hasattr(scroll, "enableTransparentBackground"):
            scroll.enableTransparentBackground()
        box = QWidget(scroll)
        vbox = QVBoxLayout(box)
        vbox.setSpacing(10)
        vbox.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(box)
        self.viewLayout.addWidget(scroll, 1)

        for a in assignments:
            card = CardWidget(box)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(8)

            top = QHBoxLayout()
            title = SubtitleLabel(a.name, card)
            top.addWidget(title, 1)
            status = CaptionLabel("已完成" if a.done else "待听写", card)
            top.addWidget(status)
            cl.addLayout(top)

            n = len(a.words) if a.words else "全部"
            meta = BodyLabel(
                f"词表：{a.wordlist_name}　范围：{n} 词　截止：{a.due_date}", card)
            cl.addWidget(meta)

            ops = QHBoxLayout()
            ops.setSpacing(8)
            export = PushButton(FluentIcon.SAVE_AS, "导出文件", card)
            export.clicked.connect(lambda _checked, asg=a: self._on_export(asg))
            ops.addWidget(export)
            # 已完成的可重置回待听写
            if a.done:
                reset = PushButton(FluentIcon.ROTATE, "重置为待听写", card)
                reset.clicked.connect(lambda _checked, aid=a.id: self._on_reset(aid))
                ops.addWidget(reset)
            del_btn = PushButton(FluentIcon.DELETE, "删除", card)
            del_btn.clicked.connect(lambda _checked, aid=a.id: self._on_delete(aid))
            ops.addWidget(del_btn)
            ops.addStretch(1)
            cl.addLayout(ops)

        self._add_sync_buttons()
        imp = PushButton(FluentIcon.DOWNLOAD, "导入布置文件…", self.widget)
        imp.clicked.connect(self._on_import)
        self.add_button(imp)
        close = PushButton("关闭", self.widget)
        close.clicked.connect(self.accept)
        self.add_button(close)

    def _on_delete(self, aid: str) -> None:
        delete_assignment(aid)
        InfoBar.info("已删除", "该布置已移除。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._rebuild()

    def _on_reset(self, aid: str) -> None:
        reset_done(aid)
        InfoBar.success("已重置", "该布置重新出现在待听写列表。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._rebuild()

    def _on_export(self, a: DictationAssignment) -> None:
        default = f"{a.name}.dictation-task.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出布置文件", default, "布置文件 (*.dictation-task.json)")
        if not path:
            return
        export_assignment_file(a, path)
        InfoBar.success("已导出", f"布置文件已保存到：{path}",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入布置文件", "", "布置文件 (*.dictation-task.json)")
        if not path:
            return
        try:
            a = import_assignment_file(path)
        except ValueError as e:
            InfoBar.error("导入失败", str(e),
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.success("已导入", f"「{a.name}」已添加到待听写。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._rebuild()

    # ------------------------------------------------------------------ GitHub 同步
    def _add_sync_buttons(self) -> None:
        """在底部加入「从 GitHub 拉取 / 上传全部」按钮。"""
        pull = PushButton(FluentIcon.DOWNLOAD, "从 GitHub 拉取", self.widget)
        pull.clicked.connect(self._on_pull)
        push = PushButton(FluentIcon.UP, "上传全部到 GitHub", self.widget)
        push.clicked.connect(self._on_upload_all)
        self.add_button(pull)
        self.add_button(push)

    def _on_pull(self) -> None:
        """教室端：从 GitHub 拉取全部任务，按 id 去重后导入本地。"""
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning(
                "未配置 GitHub", "请先在「设置 → GitHub 同步」填写仓库与 Token。",
                position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.info("正在拉取…", "正在从 GitHub 拉取听写任务。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        worker = GitHubTaskWorker(lambda: self._do_pull(sync), self)
        worker.done.connect(self._on_pull_done)
        worker.start()

    def _do_pull(self, sync: "GitHubSync") -> dict:  # type: ignore[name-defined]
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

    def _on_pull_done(self, ok: bool, payload) -> None:
        if not ok:
            InfoBar.error("拉取失败", f"{payload}",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.success(
            "拉取完成",
            f"新增 {payload['added']} 个任务，跳过已存在 {payload['skipped']} 个"
            f"（远端共 {payload['total']} 个）。",
            position=InfoBarPosition.TOP_RIGHT, parent=self)
        self._rebuild()

    def _on_upload_all(self) -> None:
        """教师端：把本地全部任务推送到 GitHub。"""
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning(
                "未配置 GitHub", "请先在「设置 → GitHub 同步」填写仓库与 Token。",
                position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.info("正在上传…", "正在把全部任务推送到 GitHub。",
                     position=InfoBarPosition.TOP_RIGHT, parent=self)
        worker = GitHubTaskWorker(lambda: self._do_upload_all(sync), self)
        worker.done.connect(self._on_upload_all_done)
        worker.attach(self).start()

    def _do_upload_all(self, sync: "GitHubSync") -> int:  # type: ignore[name-defined]
        count = 0
        for a in list_assignments():
            sync.push_task(assignment_to_dict(a))
            count += 1
        return count

    def _on_upload_all_done(self, ok: bool, payload) -> None:
        if not ok:
            InfoBar.error("上传失败", f"{payload}",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        InfoBar.success("上传完成", f"已上传 {payload} 个任务到 GitHub。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _rebuild(self) -> None:
        """删除 / 重置后重建内容（轻量刷新，避免外部调用方再开一次）。"""
        # 清空 viewLayout 全部子项后重建
        while self.viewLayout.count():
            item = self.viewLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._build_content()

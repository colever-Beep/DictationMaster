"""设置页（规范 §F5，M6 补全）。

以 ``SettingCardGroup`` 分为五组：
- 通用：主题、学科、启动时检查网络
- 语音：默认音色（语文 / 英语）、音色模式、试听、网络代理、合成并发数
- 存储：缓存目录（可改）、缓存大小显示、一键清理缓存
- 快捷键：只读说明表
- 关于：版本信息、检查更新（占位）

所有配置项直接绑定 ``app_config.cfg``，改动即时写入 ``config.json``；
涉及运行时状态的项（代理 / 缓存目录）会同步推送到 ``Services``。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    OptionsSettingCard,
    PrimaryPushSettingCard,
    PushSettingCard,
    RangeSettingCard,
    SettingCard,
    SettingCardGroup,
    StrongBodyLabel,
    SwitchSettingCard,
    TableWidget,
    qconfig,
)

import core.cache as cache
from app_config import cfg
from core.github_sync import make_github_sync
from core.paths import APP_DATA
from ui.pages.base import PageBase
from ui.widgets.github_worker import GitHubTaskWorker

# 快捷键说明（规范 §F3，只读）
_SHORTCUTS = [
    ("Space", "开始 / 暂停 / 继续听写"),
    ("←", "上一个词"),
    ("→", "下一个词（跳过）"),
    ("R", "重读本题"),
    ("Esc", "停止听写并复位状态机"),
]


class _SynthWorker(QThread):
    """后台合成 worker：直接调用 edge-tts，绕开 TTSService（设置页不一定持有服务）。

    成功时 ``done`` 携带 (True, mp3_path)；失败时携带 (False, 人类可读错误)。
    这样「语音连通性测试 / 试听」在设置页未注入 services 时也能工作，
    并能在联网失败时把 edge-tts 的真实错误（如 “No audio was received”）暴露给用户，
    而不是被离线降级静默吞掉。
    """

    done = Signal(bool, str)

    def __init__(self, text: str, voice: str, rate: str, volume: str,
                 pitch: str, proxy: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self._args = (text, voice, rate, volume, pitch, proxy or "")

    def run(self) -> None:  # noqa: D401
        import asyncio

        import edge_tts

        text, voice, rate, volume, pitch, proxy = self._args
        tmp = tempfile.mktemp(suffix=".mp3")
        try:
            comm = edge_tts.Communicate(
                text=text, voice=voice, rate=rate, volume=volume,
                pitch=pitch, proxy=proxy or None,
            )
            asyncio.run(comm.save(tmp))
        except Exception as exc:  # noqa: BLE001
            # 失败：清理临时文件并上报真实错误（含 “No audio was received” 等）
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self.done.emit(False, f"{type(exc).__name__}: {exc}"[:240])
            return
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self.done.emit(
                False, "合成返回空音频：多半是网络被拦截或代理异常（微软 TTS 不可达）。")
            return
        # 成功：把路径交给调用方；调用方负责在播放/展示后清理
        self.done.emit(True, tmp)


class _KokoroTestWorker(QThread):
    """后台校验 Kokoro 离线引擎：合成一句中文并报告结果（不依赖边缘 TTS 服务）。"""

    done = Signal(bool, str)

    def run(self) -> None:  # noqa: D401
        try:
            import kokoro  # noqa: F401
            import misaki  # noqa: F401
        except ImportError as exc:
            self.done.emit(False, f"尚未安装 Kokoro：{exc}")
            return
        try:
            import asyncio
            import os
            import tempfile

            from core.tts_backend import KokoroBackend

            out = tempfile.mktemp(suffix=".wav")
            b = KokoroBackend()
            asyncio.run(b.synth(
                text="听写测试。", voice="zh-CN-XiaoxiaoNeural",
                rate="-10%", volume="+0%", pitch="+0Hz",
                proxy="", out_path=out,
            ))
            size = os.path.getsize(out)
            os.unlink(out)
            self.done.emit(True, f"合成成功（{size} 字节），离线引擎可用。")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"{type(exc).__name__}: {exc}"[:240])


def _human_size(n: int) -> str:
    """字节数转人类可读。"""
    if n < 1024:
        return f"{n} B"
    f = float(n)
    for unit in ("KB", "MB", "GB"):
        f /= 1024
        if f < 1024 or unit == "GB":
            return f"{f:.1f} {unit}"
    return f"{f:.1f} GB"


def _safe_unlink(path: str) -> None:
    """删除临时音频文件，失败静默忽略。"""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


class SettingPage(PageBase):
    """设置页：五组设置卡片。"""

    def __init__(self, services: Optional[object] = None,
                 parent: object | None = None) -> None:
        super().__init__("设置", parent)
        self._services = services

        self._build_general()
        self._build_voice()
        self._build_storage()
        self._build_github()
        self._build_shortcuts()
        self._build_about()

    # ------------------------------------------------------------------ 通用
    def _build_general(self) -> None:
        group = SettingCardGroup("通用", self)
        # texts 顺序需与 cfg.theme.options（[LIGHT, DARK, AUTO]）一致
        group.addSettingCard(OptionsSettingCard(
            cfg.theme, FluentIcon.SETTING, "主题",
            "应用主题（浅色 / 深色 / 跟随系统），重启后保留",
            texts=["浅色", "深色", "跟随系统"], parent=group))
        # texts 顺序需与 cfg.subject.options（["chinese","english"]）一致
        group.addSettingCard(OptionsSettingCard(
            cfg.subject, FluentIcon.LIBRARY, "学科",
            "当前听写学科（语文 / 英语），影响默认音色与词表",
            texts=["语文", "英语"], parent=group))
        group.addSettingCard(SwitchSettingCard(
            FluentIcon.GLOBE, "启动时检查网络",
            "启动时轻量合成一个「测」字以探测 edge-tts 可用性；失败自动改用离线引擎",
            cfg.check_network_on_start, parent=group))
        self.add_widget(group)

    # ------------------------------------------------------------------ 语音
    def _build_voice(self) -> None:
        group = SettingCardGroup("语音", self)

        # 默认音色：音色列表是运行期拉取的，故用自定义卡片 + ComboBox
        self._zh_card = SettingCard(FluentIcon.EDUCATION, "默认音色（语文）",
                                    "语文听写使用的默认发音人", group)
        self._zh_combo = ComboBox(self._zh_card)
        self._zh_combo.setMinimumWidth(280)
        self._zh_combo.currentIndexChanged.connect(
            lambda _i: self._on_default_voice("zh"))
        self._zh_card.hBoxLayout.addWidget(self._zh_combo)
        self._zh_card.hBoxLayout.addSpacing(16)
        group.addSettingCard(self._zh_card)

        self._en_card = SettingCard(FluentIcon.GLOBE, "默认音色（英语）",
                                    "英语听写使用的默认发音人", group)
        self._en_combo = ComboBox(self._en_card)
        self._en_combo.setMinimumWidth(280)
        self._en_combo.currentIndexChanged.connect(
            lambda _i: self._on_default_voice("en"))
        self._en_card.hBoxLayout.addWidget(self._en_combo)
        self._en_card.hBoxLayout.addSpacing(16)
        group.addSettingCard(self._en_card)
        self.refresh_voices()

        # 音色模式
        group.addSettingCard(OptionsSettingCard(
            cfg.voice_mode, FluentIcon.SPEAKERS, "音色模式",
            "男女混读会在相邻词条间轮换音色，避免单调",
            texts=["女声", "男声", "男女混读"], parent=group))

        # 离线引擎（Kokoro）开关
        group.addSettingCard(SwitchSettingCard(
            FluentIcon.GLOBE, "离线引擎（Kokoro）",
            "开启后改用本地 Kokoro 离线报读，断网也能用；关闭则用在线 Edge（需联网、音质更佳）。"
            "首次使用会自动下载模型（约 90MB）。",
            cfg.kokoro_enabled, parent=group))
        cfg.kokoro_enabled.valueChanged.connect(self._on_kokoro_toggled)

        # 验证离线引擎
        self._ktest_card = PushSettingCard(
            "测试离线引擎", FluentIcon.SEARCH, "验证 Kokoro 离线引擎",
            "合成一句中文以确认 Kokoro 已正确安装并可用", parent=group)
        self._ktest_card.clicked.connect(self._on_test_kokoro)
        group.addSettingCard(self._ktest_card)
        self._ktest_busy = False

        # 听写信息播报开关
        group.addSettingCard(SwitchSettingCard(
            FluentIcon.MICROPHONE, "听写信息播报",
            "听写开始前播报词语数量、朗读次数、书写时间与「请确认音量」提示；"
            "结束后播报「听写结束」。",
            cfg.announce_enabled, parent=group))

        # 试听
        self._preview_card = PushSettingCard(
            "试听", FluentIcon.VOLUME, "试听默认音色",
            "用当前学科的默认音色合成并播放一句示例", parent=group)
        self._preview_card.clicked.connect(self.on_preview_clicked)
        group.addSettingCard(self._preview_card)

        # 语音连通性测试：直接调 edge-tts，显示真实结果/错误（排查“收不到音频”）
        self._test_card = PushSettingCard(
            "测试语音", FluentIcon.SEARCH, "语音连通性测试",
            "直接向 edge-tts 发起一次合成，显示真实结果或错误，用于排查“收不到音频”问题",
            parent=group)
        self._test_card.clicked.connect(self._on_test_voice)
        group.addSettingCard(self._test_card)
        self._busy = False

        # 网络代理
        self._proxy_card = SettingCard(
            FluentIcon.LINK, "网络代理",
            "留空则沿用系统/环境变量代理；若提示“收不到音频”，多半是无法直连微软 TTS，"
            "请在此填写可用代理，如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7890", group)
        self._proxy_edit = LineEdit(self._proxy_card)
        self._proxy_edit.setPlaceholderText("留空表示直连")
        self._proxy_edit.setClearButtonEnabled(True)
        self._proxy_edit.setMinimumWidth(280)
        self._proxy_edit.setText(str(cfg.proxy.value or ""))
        self._proxy_edit.editingFinished.connect(self._on_proxy_changed)
        self._proxy_card.hBoxLayout.addWidget(self._proxy_edit)
        self._proxy_card.hBoxLayout.addSpacing(16)
        group.addSettingCard(self._proxy_card)

        # 合成并发数（1–8）
        group.addSettingCard(RangeSettingCard(
            cfg.concurrency, FluentIcon.SYNC, "合成并发数",
            "开始听写前并发预合成整份词表的并发上限（1–8）", parent=group))

        self.add_widget(group)

    # ------------------------------------------------------------------ 存储
    def _build_storage(self) -> None:
        group = SettingCardGroup("存储", self)

        self._cache_card = PushSettingCard(
            "选择文件夹", FluentIcon.FOLDER, "缓存目录",
            f"当前：{self._cache_dir()}", parent=group)
        self._cache_card.clicked.connect(self._on_choose_cache_dir)
        group.addSettingCard(self._cache_card)

        # 缓存大小 + 清理
        self._size_card = SettingCard(FluentIcon.SAVE, "缓存大小", "", group)
        self._size_label = StrongBodyLabel("计算中…", self._size_card)
        self._size_card.hBoxLayout.addWidget(self._size_label)
        self._size_card.hBoxLayout.addSpacing(16)
        group.addSettingCard(self._size_card)

        clear_card = PushSettingCard(
            "清理缓存", FluentIcon.DELETE, "一键清理缓存",
            "删除全部已合成的 mp3（下次听写会重新联网合成）", parent=group)
        clear_card.clicked.connect(self._on_clear_cache)
        group.addSettingCard(clear_card)

        open_card = PushSettingCard(
            "打开数据目录", FluentIcon.FOLDER, "打开数据目录",
            f"词表 / 数据库 / 日志均在：{APP_DATA}", parent=group)
        open_card.clicked.connect(self._on_open_data_dir)
        group.addSettingCard(open_card)

        self.refresh_cache_size()
        self.add_widget(group)

    # ------------------------------------------------------------------ GitHub 同步
    def _build_github(self) -> None:
        group = SettingCardGroup("GitHub 同步（跨电脑分发听写任务）", self)

        group.addSettingCard(SwitchSettingCard(
            FluentIcon.CLOUD, "启用 GitHub 同步",
            "开启后，教师可在布置任务时上传到 GitHub，教室端在「待听写任务 / 管理布置」中一键拉取",
            cfg.github_enabled, parent=group))

        def add_field(label: str, icon, placeholder: str, attr: str,
                      password: bool = False, default: str = "") -> None:
            card = SettingCard(
                icon, label,
                "留空表示未设置" if not password else
                "Token 仅明文保存在本机配置中，建议使用仅限本仓库的细粒度 PAT",
                group)
            edit = LineEdit(card)
            edit.setMinimumWidth(260)
            edit.setClearButtonEnabled(True)
            edit.setPlaceholderText(placeholder)
            if password:
                edit.setEchoMode(QLineEdit.Password)
            edit.setText(str(getattr(cfg, attr).value or default))
            edit.editingFinished.connect(
                lambda c=edit, a=attr: (
                    setattr(getattr(cfg, a), "value", c.text().strip()),
                    qconfig.save(),
                ))
            card.hBoxLayout.addWidget(edit)
            card.hBoxLayout.addSpacing(16)
            group.addSettingCard(card)

        add_field("仓库拥有者 (owner)", FluentIcon.EDUCATION, "如 teacher-lee",
                  "github_owner")
        add_field("仓库名 (repo)", FluentIcon.LIBRARY, "dictation-tasks",
                  "github_repo")
        add_field("分支 (branch)", FluentIcon.CODE, "main", "github_branch",
                  default="main")
        add_field("Personal Access Token", FluentIcon.LINK,
                  "ghp_xxx 或 github_pat_xxx", "github_token", password=True)
        add_field("任务目录", FluentIcon.FOLDER, "tasks", "github_tasks_path",
                  default="tasks")

        # ---- 上传默认设置 ----
        group.addSettingCard(SwitchSettingCard(
            FluentIcon.UP, "布置后自动上传",
            "开启后，在「布置听写」中点「布置」会自动把任务推送到上面的任务目录"
            "（上传失败不影响本地保存）",
            cfg.github_auto_upload, parent=group))
        group.addSettingCard(SwitchSettingCard(
            FluentIcon.SYNC, "上传时覆盖同名任务",
            "关闭后，仓库中已存在同一任务时跳过不覆盖，保留教室端已有内容",
            cfg.github_upload_overwrite, parent=group))

        init_card = PushSettingCard(
            "初始化目录", FluentIcon.FOLDER, "在仓库创建任务目录",
            "在仓库中生成任务目录（含说明文件），确保教室端可直接拉取", parent=group)
        init_card.clicked.connect(self._on_init_github_folder)
        group.addSettingCard(init_card)

        test_card = PushSettingCard(
            "测试连接", FluentIcon.SEARCH, "测试 GitHub 连接",
            "验证仓库是否存在且 Token 有访问权限", parent=group)
        test_card.clicked.connect(self._on_test_github)
        group.addSettingCard(test_card)
        self.add_widget(group)
        self._github_busy = False

    def _on_init_github_folder(self) -> None:
        """在仓库里创建任务目录（写占位 README），让教室端第一次拉取就有目录。"""
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning("未配置", "请先填写 owner / repo（Token 可选，公开仓库可不填）。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        btn = getattr(self.sender(), "button", None)
        if btn is not None:
            btn.setText("创建中…")
        worker = GitHubTaskWorker(sync.ensure_folder, self)
        worker.done.connect(
            lambda ok, payload, b=btn: self._on_init_folder_done(ok, payload, b))
        worker.attach(self).start()

    def _on_init_folder_done(self, ok: bool, payload, btn) -> None:
        if btn is not None:
            btn.setText("初始化目录")
        if not ok:
            InfoBar.error("初始化失败", f"{payload}", duration=6000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        path = cfg.github_tasks_path.value or "tasks"
        if payload == "created":
            InfoBar.success("已创建", f"仓库中已生成任务目录「{path}」，教室端可直接拉取。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.info("目录已存在", f"仓库中已有任务目录「{path}」，无需重复创建。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_test_github(self) -> None:
        if self._github_busy:
            return
        sync = make_github_sync()
        if sync is None:
            InfoBar.warning("未配置", "请先填写 owner / repo（Token 可选，公开仓库可不填）。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        self._github_busy = True
        self._test_github_card = self.sender()
        self._github_test_btn = getattr(self._test_github_card, "button", None)
        if self._github_test_btn is not None:
            self._github_test_btn.setText("测试中…")
        worker = GitHubTaskWorker(sync.test_connection, self)
        worker.done.connect(self._on_test_github_done)
        worker.attach(self).start()

    def _on_test_github_done(self, ok: bool, payload) -> None:
        self._github_busy = False
        if self._github_test_btn is not None:
            self._github_test_btn.setText("测试连接")
        if not ok:
            InfoBar.error("连接失败", f"{payload}",
                          duration=6000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        conn_ok, msg = payload  # test_connection 返回 (bool, str)
        if conn_ok:
            InfoBar.success("连接成功", msg,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.warning("连接异常", msg,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ------------------------------------------------------------------ 快捷键
    def _build_shortcuts(self) -> None:
        group = SettingCardGroup("快捷键", self)
        host = QWidget(group)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(16, 12, 16, 12)
        table = TableWidget(host)
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["按键", "功能"])
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setRowCount(len(_SHORTCUTS))
        for r, (key, desc) in enumerate(_SHORTCUTS):
            table.setItem(r, 0, QTableWidgetItem(key))
            table.setItem(r, 1, QTableWidgetItem(desc))
            table.setRowHeight(r, 36)
        table.setFixedHeight(36 * len(_SHORTCUTS) + 44)
        lay.addWidget(table)
        group.addSettingCard(host)
        self.add_widget(group)

    # ------------------------------------------------------------------ 关于
    def _build_about(self) -> None:
        group = SettingCardGroup("关于", self)
        group.addSettingCard(SettingCard(
            FluentIcon.INFO, "版本信息", self._version_text(), group))
        update_card = PrimaryPushSettingCard(
            "检查更新", FluentIcon.UPDATE, "检查更新",
            "当前为离线版本，更新检查功能将在后续版本提供", parent=group)
        update_card.clicked.connect(
            lambda: InfoBar.info("暂未实现", "更新检查将在后续版本提供。",
                                 position=InfoBarPosition.TOP_RIGHT, parent=self))
        group.addSettingCard(update_card)
        self.add_widget(group)

    # ------------------------------------------------------------------ 工具
    def _version_text(self) -> str:
        try:
            from PySide6 import __version__ as pyside_ver
        except Exception:  # noqa: BLE001
            pyside_ver = "unknown"
        try:
            import edge_tts
            edge_ver = edge_tts.__version__
        except Exception:  # noqa: BLE001
            edge_ver = "unknown"
        try:
            import qfluentwidgets
            qf_ver = qfluentwidgets.__version__
        except Exception:  # noqa: BLE001
            qf_ver = "unknown"
        return (f"听写助手 0.6.0 · PySide6 {pyside_ver} · "
                f"qfluentwidgets {qf_ver} · edge-tts {edge_ver}")

    def _cache_dir(self) -> str:
        if self._services is not None:
            try:
                return str(self._services.tts.cache_dir())
            except Exception:  # noqa: BLE001
                pass
        return str(cfg.cache_dir.value)

    # ------------------------------------------------------------------ 音色
    def refresh_voices(self) -> None:
        """把音色列表填入两个下拉框，并选中当前配置值。"""
        voices = []
        if self._services is not None:
            try:
                voices = list(self._services.voices.current())
            except Exception:  # noqa: BLE001
                voices = []
        if not voices:
            from core.voice import builtin_voices
            voices = builtin_voices()

        def fill(combo: ComboBox, prefix: str, current: str) -> None:
            combo.blockSignals(True)
            combo.clear()
            for v in voices:
                if v.locale.startswith(prefix):
                    combo.addItem(v.friendly, userData=v.short_name)
            idx = combo.findData(current)
            if idx < 0:
                # 当前配置的音色不在列表里（例如已下线），补一条以保证可见
                combo.addItem(current, userData=current)
                idx = combo.findData(current)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

        fill(self._zh_combo, "zh", str(cfg.default_voice_zh.value))
        fill(self._en_combo, "en", str(cfg.default_voice_en.value))

    def _on_default_voice(self, lang: str) -> None:
        combo = self._zh_combo if lang == "zh" else self._en_combo
        short = combo.currentData()
        if not short:
            return
        item = cfg.default_voice_zh if lang == "zh" else cfg.default_voice_en
        if item.value == short:
            return
        item.value = str(short)
        qconfig.save()

    def on_preview_clicked(self) -> None:
        """试听：用当前学科默认音色合成一句并播放。"""
        if self._services is not None:
            voice = str(cfg.default_voice_zh.value if cfg.subject.value == "chinese"
                        else cfg.default_voice_en.value)
            text = "听写助手，这是默认音色的试听效果。"
            # 只连接一次，避免重复播放
            if not getattr(self, "_preview_wired", False):
                self._services.tts.single_ready.connect(
                    lambda rid, path: self._services.player.play_file(path)
                    if rid == "__preview__" else None)
                self._services.tts.single_failed.connect(
                    lambda rid, err: InfoBar.warning(
                        "试听失败（可尝试离线引擎）", err,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
                    if rid == "__preview__" else None)
                self._preview_wired = True
            self._services.tts.synthesize("__preview__", text, voice,
                                          str(cfg.rate.value), str(cfg.volume.value),
                                          str(cfg.pitch.value))
            InfoBar.info("正在试听", f"音色：{voice}", duration=2000,
                         position=InfoBarPosition.TOP_RIGHT, parent=self)
            return

        # 设置页未注入 services 时，本地直接合成并播放（不再是无用的死按钮）
        if self._busy:
            return
        self._busy = True
        self._preview_card.button.setText("试听中…")
        subject = cfg.subject.value
        voice = str(cfg.default_voice_zh.value if subject == "chinese"
                    else cfg.default_voice_en.value)
        w = _SynthWorker("听写助手，这是默认音色的试听效果。", voice,
                         str(cfg.rate.value), str(cfg.volume.value),
                         str(cfg.pitch.value), str(cfg.proxy.value or ""), self)
        w.done.connect(self._on_preview_synth)
        w.start()

    def _on_preview_synth(self, ok: bool, msg: str) -> None:
        self._busy = False
        self._preview_card.button.setText("试听")
        if not ok:
            InfoBar.warning("试听失败", msg, duration=6000,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        # 用 QMediaPlayer 播放临时文件，播放结束后清理
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QMediaPlayer, QUrl

        player = QMediaPlayer(self)
        player.setSource(QUrl.fromLocalFile(msg))
        player.play()
        QTimer.singleShot(12000, lambda: (player.stop(), _safe_unlink(msg)))

    # ------------------------------------------------------------------ 语音测试
    def _current_voice(self) -> str:
        subject = cfg.subject.value
        return str(cfg.default_voice_zh.value if subject == "chinese"
                   else cfg.default_voice_en.value)

    def _on_test_voice(self) -> None:
        """语音连通性测试：直接调 edge-tts，显示真实结果或错误。"""
        if self._busy:
            return
        self._busy = True
        self._test_card.button.setText("测试中…")
        w = _SynthWorker("听写助手语音测试。", self._current_voice(),
                         str(cfg.rate.value), str(cfg.volume.value),
                         str(cfg.pitch.value), str(cfg.proxy.value or ""), self)
        w.done.connect(self._on_voice_test_done)
        w.start()

    def _on_voice_test_done(self, ok: bool, msg: str) -> None:
        self._busy = False
        self._test_card.button.setText("测试语音")
        if ok:
            size = os.path.getsize(msg) if os.path.exists(msg) else 0
            InfoBar.success("语音测试通过", f"已成功合成音频（{size} 字节），"
                            "说明网络与参数均正常。", duration=4000,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
            _safe_unlink(msg)
        else:
            InfoBar.error("语音测试失败", msg, duration=8000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ------------------------------------------------------------------ 离线引擎
    def _check_kokoro(self):
        try:
            import kokoro  # noqa: F401
            import misaki  # noqa: F401
            return True, "已安装"
        except ImportError as exc:
            return False, f"尚未安装 Kokoro，请执行：pip install kokoro misaki[zh]（{exc}）"

    def _on_kokoro_toggled(self, value) -> None:
        if self._services is not None:
            self._services.tts.set_engine("kokoro" if value else "edge")
        if value:
            ok, msg = self._check_kokoro()
            if not ok:
                InfoBar.warning("Kokoro 未就绪", msg, duration=6000,
                                position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_test_kokoro(self) -> None:
        if self._ktest_busy:
            return
        self._ktest_busy = True
        self._ktest_card.button.setText("测试中…")
        w = _KokoroTestWorker(self)
        w.done.connect(self._on_test_kokoro_done)
        w.start()

    def _on_test_kokoro_done(self, ok: bool, msg: str) -> None:
        self._ktest_busy = False
        self._ktest_card.button.setText("测试离线引擎")
        if ok:
            InfoBar.success("离线引擎可用", msg, duration=4000,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.warning("离线引擎不可用", msg, duration=8000,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ------------------------------------------------------------------ 槽
    def _on_proxy_changed(self) -> None:
        cfg.proxy.value = self._proxy_edit.text().strip()
        qconfig.save()
        if self._services is not None:
            self._services.apply_config(cfg)
        InfoBar.success("已保存", "代理设置已生效（下次合成使用）。", duration=2000,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_choose_cache_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择缓存目录",
                                                self._cache_dir())
        if not path:
            return
        cfg.cache_dir.value = path
        qconfig.save()
        if self._services is not None:
            try:
                self._services.tts.set_cache_dir(path)
            except Exception:  # noqa: BLE001
                pass
        self._cache_card.setContent(f"当前：{path}")
        self.refresh_cache_size()
        InfoBar.success("缓存目录已更新", path,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_clear_cache(self) -> None:
        base = Path(self._cache_dir())
        n = cache.clear(base)
        self.refresh_cache_size()
        InfoBar.success("缓存已清理", f"删除 {n} 个音频文件。",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_open_data_dir(self) -> None:
        try:
            os.startfile(str(APP_DATA))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            InfoBar.warning("无法打开目录", f"{APP_DATA}\n{exc}",
                            position=InfoBarPosition.TOP_RIGHT, parent=self)

    def refresh_cache_size(self) -> None:
        base = Path(self._cache_dir())
        size = cache.total_size(base)
        cnt = cache.count(base)
        self._size_label.setText(f"{_human_size(size)}（{cnt} 个文件）")
        self._size_card.setContent(f"目录：{base}")

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

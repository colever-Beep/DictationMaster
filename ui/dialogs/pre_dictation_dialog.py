"""听前信息确认弹窗（规范 §F3 听前提醒）。

在正式开始听写之前，用可视化的方式把本次听写的核心设置一次性展示给用户确认，
与「听写信息播报」语音（开场 TTS）形成「看得见 + 听得见」的双重提醒。

入口统一在 ``ui/pages/dictation_page.py`` 的 ``_begin_session``：先弹此窗，
用户点「开始听写」才真正 ``engine.start()``；点「取消」则退回当前页面、不启动。

``build_session_summary`` 为纯函数（不依赖 Qt），方便单测。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from core.dictation_engine import PlayConfig, estimate_dictation_minutes
from data.models import WordList
from ui.dialogs.base import FluentContentDialog


_SUBJECT_LABEL = {"chinese": "语文", "english": "英语"}


def build_session_summary(wl: WordList, cfg: PlayConfig) -> list[tuple[str, str]]:
    """生成本次听写的核心信息（标签 → 值），顺序即两列网格的排布顺序。

    只保留用户关心的 6 项：左列「学科 / 词语数量 / 书写时间」，
    右列「词表 / 朗读次数 / 预计时长」。
    """
    subject = _SUBJECT_LABEL.get(cfg.subject, cfg.subject)
    n = len(wl.items)
    rep = cfg.repeat
    iv = cfg.interval
    est = estimate_dictation_minutes(n, rep, cfg.inner_pause, iv)
    time_hint = f"约 {est} 分钟" if est >= 1 else "不到 1 分钟"

    return [
        ("学科", subject),
        ("词表", wl.name or "（未命名）"),
        ("词语数量", f"{n} 个"),
        ("朗读次数", f"{rep} 遍"),
        ("书写时间", f"{iv:.0f} 秒/词"),
        ("预计时长", time_hint),
    ]


class PreDictationDialog(FluentContentDialog):
    """听前信息确认弹窗：一次性展示核心设置，确认后才开始。"""

    def __init__(self, wl: WordList, cfg: PlayConfig,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("本次听写信息", parent)
        self.setMinimumWidth(520)

        intro = BodyLabel(
            "请确认以下听写设置，点击「开始听写」正式开始。", self.widget)
        intro.setWordWrap(True)
        self.viewLayout.addWidget(intro)

        # 信息网格：两列成对排布（左 key/val，右 key/val），一次全部呈现
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        for i, (key, value) in enumerate(build_session_summary(wl, cfg)):
            r = i // 2
            c = (i % 2) * 2
            klabel = BodyLabel(key, self.widget)
            klabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vlabel = StrongBodyLabel(value, self.widget)
            vlabel.setWordWrap(True)
            vlabel.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(klabel, r, c)
            grid.addWidget(vlabel, r, c + 1)

        self.viewLayout.addLayout(grid)

        # 底部按钮
        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("开始听写", self.widget)
        ok.setIcon(FluentIcon.PLAY)
        ok.clicked.connect(self.accept)
        self.add_button(cancel)
        self.add_button(ok)
        ok.setFocus()

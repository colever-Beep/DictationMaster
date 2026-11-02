"""离线降级 TTS：封装 ``PySide6.QtTextToSpeech``（Windows SAPI 本地引擎）。

对应规范 §1 硬性约束 / §8.2.6：网络不可用或 edge-tts 连续失败时，用本地语音引擎兜底，
保证课堂场景至少能出声。该引擎走系统 SAPI，无需联网、无需预合成、无缓存。

注意：本模块**绝不** import 任何 ``ui``；只发信号，由 UI 连接处理。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtTextToSpeech import QTextToSpeech

logger = logging.getLogger(__name__)


class FallbackTTS(QObject):
    """离线 TTS 封装（QtTextToSpeech / SAPI）。"""

    said_finished = Signal()        # 一段文本播报完成
    say_error = Signal(str)         # 错误（无可用引擎 / 播报失败）

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = QTextToSpeech(self)
        self._speaking = False
        self._engine.stateChanged.connect(self._on_state)
        self._engine.errorOccurred.connect(lambda err: self.say_error.emit(str(err)))

    def say(self, text: str, subject: str = "chinese") -> None:
        """播报文本。``subject`` 用于挑选更贴近的系统语音（中文 / 英语）。"""
        if not text:
            return
        if not self._engine.availableLocales():
            self.say_error.emit("系统未找到可用的离线语音引擎（SAPI）")
            return
        # 尽量匹配学科语言，提升离线读音自然度
        target = "zh" if subject == "chinese" else "en"
        matched = None
        for loc in self._engine.availableLocales():
            if loc.name().lower().startswith(target):
                matched = loc
                break
        if matched is not None:
            self._engine.setLocale(matched)
        self._speaking = True
        self._engine.say(text)

    def stop(self) -> None:
        self._speaking = False
        self._engine.stop()

    def is_available(self) -> bool:
        return bool(self._engine.availableLocales())

    def _on_state(self, state: QTextToSpeech.State) -> None:
        # 播报从 Speaking 回到 Ready 视为完成（初始 Ready 不触发）
        if state == QTextToSpeech.State.Ready and self._speaking:
            self._speaking = False
            self.said_finished.emit()

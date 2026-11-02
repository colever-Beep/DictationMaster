"""音色管理：从 ``edge_tts.list_voices()`` 拉取并过滤，离线时回退到内置列表。

对应规范 §7：音色列表**不硬编码为唯一数据源**——首次运行联网拉取，按 locale 前缀
（``zh-CN`` / ``en-US`` / ``en-GB``）过滤；接口不可用时回退到内置表（§7 列出）。
缓存持久化（``voice_cache`` 表）属 M5，本模块只负责「拉取 + 内置兜底」。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

import edge_tts

logger = logging.getLogger(__name__)

# 规范 §7 内置音色表（离线兜底用）
_BUILTIN: list[dict] = [
    # 中文（语文听写）
    {"short_name": "zh-CN-XiaoxiaoNeural", "locale": "zh-CN", "gender": "女", "friendly": "晓晓（默认女声·温柔清晰）"},
    {"short_name": "zh-CN-XiaoyiNeural", "locale": "zh-CN", "gender": "女", "friendly": "晓伊（活泼·低年级）"},
    {"short_name": "zh-CN-YunxiNeural", "locale": "zh-CN", "gender": "男", "friendly": "云希（默认男声·少年感）"},
    {"short_name": "zh-CN-YunjianNeural", "locale": "zh-CN", "gender": "男", "friendly": "云健（沉稳·长篇解说）"},
    {"short_name": "zh-CN-YunyangNeural", "locale": "zh-CN", "gender": "男", "friendly": "云扬（新闻播音腔）"},
    {"short_name": "zh-CN-liaoning-XiaobeiNeural", "locale": "zh-CN-liaoning", "gender": "女", "friendly": "辽宁晓贝（东北方言）"},
    {"short_name": "zh-CN-shaanxi-XiaoniNeural", "locale": "zh-CN-shaanxi", "gender": "女", "friendly": "陕西小妮（陕西方言）"},
    # 英语（英语单词听写）
    {"short_name": "en-US-AriaNeural", "locale": "en-US", "gender": "女", "friendly": "Aria（美式·女）"},
    {"short_name": "en-US-AnaNeural", "locale": "en-US", "gender": "童声", "friendly": "Ana（美式·童声）"},
    {"short_name": "en-US-GuyNeural", "locale": "en-US", "gender": "男", "friendly": "Guy（美式·男）"},
    {"short_name": "en-US-JennyNeural", "locale": "en-US", "gender": "女", "friendly": "Jenny（美式·女）"},
    {"short_name": "en-GB-SoniaNeural", "locale": "en-GB", "gender": "女", "friendly": "Sonia（英式·女）"},
    {"short_name": "en-GB-RyanNeural", "locale": "en-GB", "gender": "男", "friendly": "Ryan（英式·男）"},
]

# 默认混读音色（规范 §7 末尾）
_DEFAULT_ZH = ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"]
_DEFAULT_EN = ["en-US-AriaNeural", "en-US-GuyNeural"]


@dataclass
class VoiceInfo:
    """单个音色信息。"""

    short_name: str
    locale: str
    gender: str
    friendly: str


def builtin_voices() -> list[VoiceInfo]:
    """返回内置音色表（离线兜底）。"""
    return [_row_to_voice(r) for r in _BUILTIN]


def _row_to_voice(r: dict) -> VoiceInfo:
    return VoiceInfo(
        short_name=r["short_name"],
        locale=r["locale"],
        gender=r["gender"],
        friendly=r["friendly"],
    )


def default_voices(subject: str, mode: str = "mixed") -> list[str]:
    """返回某学科的默认音色列表。

    ``mode``: ``female`` 取第一个女声；``male`` 取第一个男声；``mixed`` 取女+男混读对。
    """
    base = _DEFAULT_ZH if subject == "chinese" else _DEFAULT_EN
    if mode == "female":
        return [base[0]]
    if mode == "male":
        return [base[1]] if len(base) > 1 else [base[0]]
    return base  # mixed


class _FetchThread(QThread):
    """后台线程：在一独立事件循环里调用 ``edge_tts.list_voices()``。

    注意：不占用 Qt 主线程，也不依赖 TTSService 的常驻 loop（一次性拉取）。
    """

    def __init__(self, proxy: Optional[str], locale_prefixes: tuple[str, ...],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proxy = proxy
        self._prefixes = locale_prefixes
        self.result: list[VoiceInfo] = []

    def run(self) -> None:
        try:
            voices = asyncio.run(edge_tts.list_voices(proxy=self._proxy))
            picked: list[VoiceInfo] = []
            for v in voices:
                loc = getattr(v, "Locale", "") or ""
                if any(loc.startswith(p) for p in self._prefixes):
                    picked.append(VoiceInfo(
                        short_name=getattr(v, "ShortName", ""),
                        locale=loc,
                        gender=str(getattr(v, "Gender", "")),
                        friendly=getattr(v, "FriendlyName", "") or getattr(v, "ShortName", ""),
                    ))
            # 按 locale 稳定排序，便于下拉展示
            picked.sort(key=lambda x: (x.locale, x.short_name))
            self.result = picked
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取音色列表失败，将回退内置表：%s", exc)
            self.result = []


class VoiceManager(QObject):
    """音色列表管理：联网拉取 + 内置兜底。"""

    voices_ready = Signal(list)      # list[VoiceInfo]
    voices_failed = Signal(str)      # error_message

    def __init__(self, locale_prefixes: tuple[str, ...] = ("zh-CN", "en-US", "en-GB"),
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._prefixes = locale_prefixes
        self._proxy: Optional[str] = None
        self._voices: list[VoiceInfo] = builtin_voices()  # 先以内置表兜底

    def set_proxy(self, proxy: str) -> None:
        self._proxy = proxy or None

    def current(self) -> list[VoiceInfo]:
        """当前可用音色（内置兜底或联网拉取结果）。"""
        return self._voices

    def fetch(self, force: bool = False) -> None:
        """异步拉取音色列表；成功经 ``voices_ready`` 返回，失败回退内置并经 ``voices_failed`` 通知。"""
        if force and self._voices != builtin_voices():
            # 已联网过且非强制：直接复用
            self.voices_ready.emit(self._voices)
            return
        thread = _FetchThread(self._proxy, self._prefixes, self)
        thread.finished.connect(lambda: self._on_fetched(thread))
        thread.start()

    def _on_fetched(self, thread: _FetchThread) -> None:
        result = thread.result
        if result:
            self._voices = result
            self.voices_ready.emit(result)
        else:
            # 拉取失败：保留内置兜底，并通知 UI（可选弹 InfoBar）
            self.voices_failed.emit("联网拉取音色失败，已使用内置列表")
            self.voices_ready.emit(self._voices)

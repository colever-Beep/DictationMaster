"""TTS 后端抽象层：把「把一条文本合成到音频文件」的具体实现（edge-tts / kokoro）
与 ``TTSService`` 的缓存、并发、重试、信号逻辑解耦。

后端统一接口（协程）：
    async def synth(self, *, text, voice, rate, volume, pitch, proxy, out_path) -> None
其中 ``out_path`` 由 ``TTSService`` 按后端后缀（.mp3 / .wav）预先确定；
``rate/volume/pitch`` 为 edge 风格字符串（如 "+0%" / "-10%" / "+0Hz"）。
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """后端合成失败的统一异常（由 TTSService 包装为 failed 信号）。"""


class BaseBackend:
    suffix = ".mp3"
    name = "base"

    async def synth(self, *, text, voice, rate, volume, pitch, proxy, out_path):  # noqa: D401
        raise NotImplementedError


class EdgeBackend(BaseBackend):
    """基于 edge-tts 的在线后端（需联网，音质最佳）。"""

    suffix = ".mp3"
    name = "edge"

    async def synth(self, *, text, voice, rate, volume, pitch, proxy, out_path):
        import edge_tts

        comm = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, volume=volume,
            pitch=pitch, proxy=proxy or None,
        )
        await comm.save(str(out_path))


class KokoroBackend(BaseBackend):
    """基于 Kokoro 的本地离线后端（无需联网，首次需下载模型，约 90MB）。

    通过 lazy import 隔离重依赖：未安装 kokoro 时不影响应用启动与在线引擎。
    中文 lang 'z'、美英 'a'、英英 'b'；音色按性别兜底；支持语速，音量按幅度缩放。
    """

    suffix = ".wav"
    name = "kokoro"

    # edge 音色 -> (kokoro 音色, 性别 f/m)；中文 lang 'z'，美英 'a'，英英 'b'
    _VOICE_MAP = {
        "zh-CN-XiaoxiaoNeural": ("zf_001", "f"),
        "zh-CN-XiaoyiNeural": ("zf_002", "f"),
        "zh-CN-YunxiNeural": ("zm_001", "m"),
        "zh-CN-YunjianNeural": ("zm_002", "m"),
        "zh-CN-YunyangNeural": ("zm_002", "m"),
        "en-US-AriaNeural": ("af_heart", "f"),
        "en-US-AnaNeural": ("af_heart", "f"),
        "en-US-GuyNeural": ("am_onyx", "m"),
        "en-US-JennyNeural": ("af_sky", "f"),
        "en-GB-SoniaNeural": ("bf_emma", "f"),
        "en-GB-RyanNeural": ("bm_george", "m"),
    }
    # 各语言的性别前缀（用于按性别兜底）
    _GENDER_PREFIX = {
        "z": {"f": "zf", "m": "zm"},
        "a": {"f": "af", "m": "am"},
        "b": {"f": "bf", "m": "bm"},
    }
    _DEFAULT_VOICE = {"z": "zf_001", "a": "af_heart", "b": "bf_emma"}

    _pipelines: dict = {}  # 按 lang_code 缓存，避免重复加载模型

    # ---- 参数解析 ----
    @staticmethod
    def _parse_pct(value: str, default: float) -> float:
        """把 "+10%" / "-10%" 解析为 1.1 / 0.9；非法返回 default。"""
        m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)\s*%", value or "")
        if not m:
            return default
        return 1.0 + float(m.group(1)) / 100.0

    def _lang_code(self, voice: str) -> str:
        if voice.startswith("zh"):
            return "z"
        if voice.startswith("en-GB"):
            return "b"
        return "a"

    def _pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            try:
                from kokoro import KPipeline
            except ImportError as exc:  # pragma: no cover - 依赖可选
                raise TTSError(
                    "未安装 Kokoro 离线引擎，请先执行：pip install kokoro misaki[zh]"
                ) from exc
            self._pipelines[lang_code] = KPipeline(lang_code=lang_code)
        return self._pipelines[lang_code]

    def _resolve_voice(self, pipeline, edge_voice: str, lang_code: str) -> str:
        entry = self._VOICE_MAP.get(edge_voice)
        gender = entry[1] if entry else "f"
        mapped = entry[0] if entry else None
        avail = []
        try:
            avail = list(getattr(pipeline, "voices", {}).get(lang_code, []))
        except Exception:  # noqa: BLE001
            avail = []
        if mapped and (not avail or mapped in avail):
            return mapped
        prefix = self._GENDER_PREFIX.get(lang_code, {}).get(gender, "f")
        for v in avail:
            if v.startswith(prefix):
                return v
        if avail:
            return avail[0]
        if mapped:
            return mapped
        return self._DEFAULT_VOICE[lang_code]

    # ---- 合成 ----
    async def synth(self, *, text, voice, rate, volume, pitch, proxy, out_path):
        lang = self._lang_code(voice)
        pipeline = self._pipeline(lang)
        kvoice = self._resolve_voice(pipeline, voice, lang)
        speed = self._parse_pct(rate, 1.0)
        vol = self._parse_pct(volume, 1.0)

        def _run() -> None:
            import numpy as np

            chunks = []
            for _g, _p, audio in pipeline(text, voice=kvoice, speed=speed):
                chunks.append(np.asarray(audio, dtype=np.float32))
            if not chunks:
                raise TTSError("Kokoro 未产出音频（空结果）")
            audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            audio = np.clip(audio, -1.0, 1.0)
            if vol != 1.0:
                audio = np.clip(audio * vol, -1.0, 1.0)
            self._write_wav(out_path, audio, 24000)

        await asyncio.to_thread(_run)

    @staticmethod
    def _write_wav(path, audio, sample_rate: int) -> None:
        """用标准库 wave 写 16-bit PCM WAV（避免额外依赖 soundfile）。"""
        import wave

        import numpy as np

        data = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(data.tobytes())


# 便捷工厂：按名字取得后端实例
def make_backend(name: str) -> BaseBackend:
    if name == "kokoro":
        return KokoroBackend()
    return EdgeBackend()

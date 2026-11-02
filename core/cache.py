"""音频缓存：key 计算、目录管理、容量统计与清理。

缓存 key 覆盖 engine|voice|rate|volume|pitch|text 维度；改语速等参数会产生
新缓存属预期行为。断网时旧音频仍可播放，是课堂场景的兜底能力。
（合成逻辑在 M2 的 tts_service 中实现，这里只负责缓存的存取与统计。）

注意：缓存目录可由用户配置（规范 §F5 存储），因此所有函数均接受可选的
``base`` 参数，缺省使用全局 ``CACHE_DIR``；``TTSService`` 会传入自身持有的缓存目录，
保证「用户改缓存目录」生效。

不同 TTS 引擎产出不同后缀（edge->.mp3，kokoro->.wav），``cache_path``/``has``
接受 ``suffix`` 参数；统计类函数（total_size/count/clear）一并覆盖 .mp3 与 .wav。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.paths import CACHE_DIR

_SUFFIXES = (".mp3", ".wav")


def cache_key(text: str, voice: str, rate: str, volume: str, pitch: str,
              engine: str = "edge") -> str:
    """计算某条合成的缓存键（sha1 十六进制）。

    ``engine="edge"`` 时复用历史 key 格式（无引擎前缀），以兼容已存在的缓存；
    其它引擎在 key 中带引擎名，避免与 edge 缓存冲突。
    """
    if engine == "edge":
        raw = f"{voice}|{rate}|{volume}|{pitch}|{text}"
    else:
        raw = f"{engine}|{voice}|{rate}|{volume}|{pitch}|{text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _dir(base: Path | None = None) -> Path:
    return Path(base) if base is not None else Path(CACHE_DIR)


def cache_path(key: str, base: Path | None = None, suffix: str = ".mp3") -> Path:
    """由缓存键与后缀得到音频路径。"""
    return _dir(base) / f"{key}{suffix}"


def has(key: str, base: Path | None = None, suffix: str = ".mp3") -> bool:
    """缓存是否存在且非空。"""
    p = cache_path(key, base, suffix)
    return p.exists() and p.stat().st_size > 0


def total_size(base: Path | None = None) -> int:
    """缓存目录总字节数（含 .mp3 与 .wav）。"""
    total = 0
    for ext in _SUFFIXES:
        for p in _dir(base).glob(f"*{ext}"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def count(base: Path | None = None) -> int:
    """缓存文件数量（含 .mp3 与 .wav）。"""
    return sum(1 for ext in _SUFFIXES for _ in _dir(base).glob(f"*{ext}"))


def clear(base: Path | None = None) -> int:
    """清空音频缓存，返回实际删除的文件数（含 .mp3 与 .wav）。"""
    n = 0
    for ext in _SUFFIXES:
        for p in _dir(base).glob(f"*{ext}"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n

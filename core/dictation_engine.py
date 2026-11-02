"""听写状态机（核心纯逻辑层，绝不 import 任何 ui 模块）。

对应规范 §3 / §F3：用显式状态机驱动整场听写，禁止用 ``sleep`` 串联流程。
所有等待与倒计时一律使用 ``QTimer`` / ``QElapsedTimer``，播放完成以
``AudioPlayer.finished``（或离线 ``FallbackTTS.said_finished``）信号为准。

状态流转（与 §F3 一致）：

    IDLE
      └─(start)→ PREPARING  并发预合成整表，汇报进度
            └─(全部就绪)→ COUNTDOWN  3→2→1（可关提示音）
                  └─(循环每个词 n 次)→ SPEAKING   播放第 k 遍
                         └─(播放结束)→ INNER_GAP  短停 inner_pause
                                └─(k<次数)→ SPEAKING 第 k+1 遍
                                       └─(k=次数)→ WRITING   书写倒计时 interval
                                            ├─(用户点下一个/重读/上一个/跳过)
                                            └─(倒计时归零)→ 下一个词
      └─(最后一个词结束)→ FINISHED  结束提示音 → 结果页
    任意状态 ──(stop / Esc)──→ IDLE
    任意状态 ──(pause)──→ PAUSED（冻结播放器与计时器，resume 原地恢复）
"""

from __future__ import annotations

import logging
import math
import struct
import random
import wave
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from core.paths import DATA_DIR
from data.models import SpeakParams, WordItem, WordList

logger = logging.getLogger(__name__)

# 开场/结束播报文本是中文，必须用中文音色；英语听写时 cfg.voices 是英文嗓音，
# 拿它念中文只会漏出数字（听起来像 "one two ten one"），故固定回退中文音色。
_ANNOUNCE_VOICE = "zh-CN-XiaoxiaoNeural"


class EngineState(str, Enum):
    """听写引擎状态。"""

    IDLE = "idle"
    PREPARING = "preparing"
    ANNOUNCING = "announcing"
    COUNTDOWN = "countdown"
    SPEAKING = "speaking"
    INNER_GAP = "inner_gap"
    WRITING = "writing"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class PlayConfig:
    """一次听写的完整报读配置（由 UI 的 param_card 根据 cfg + 学科拼装）。"""

    subject: str = "chinese"
    rate: str = "-10%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    repeat: int = 2
    interval: float = 10.0
    inner_pause: float = 1.5
    shuffle: bool = False
    loop: bool = False
    countdown_beep: bool = True
    word_beep: bool = False
    end_beep: bool = True
    paper_mode: bool = True
    show_answer_at_end: bool = True
    voices: list[str] = field(default_factory=list)   # 已按学科解析好的音色列表
    concurrency: int = 4
    announce: bool = True                              # 听写前后信息播报
    seed: Optional[int] = None                          # 固定随机种子可复现乱序


def make_beep_wav(path: Path, freq: float = 880.0, duration: float = 0.12,
                  sample_rate: int = 44100) -> None:
    """生成一段极短的正弦提示音 WAV（用于倒计时 / 结束提示）。纯标准库实现。"""
    n = int(sample_rate * duration)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n):
            # 0.4 幅度避免爆音；左右对称正弦
            val = int(32767 * 0.4 * math.sin(2 * math.pi * freq * i / sample_rate))
            w.writeframes(struct.pack("<h", val))


def estimate_dictation_minutes(n: int, repeat: int,
                               inner_pause: float, interval: float) -> int:
    """估算整场听写耗时（分钟），与开场语音播报保持一致。

    ``repeat * 2`` 近似每遍报读约 2 秒，叠加词间停顿与书写时间后除以 60。
    返回至少 1 分钟。
    """
    return max(1, round(n * (repeat * 2 + inner_pause + interval) / 60))


class DictationEngine(QObject):
    """听写状态机：驱动预合成、倒计时、逐词报读、书写倒计时与暂停恢复。

    本类只依赖注入进来的 ``tts`` / ``player`` / ``fallback`` 服务（均为 core 层对象），
    通过信号把状态变化广播给 UI；自身不创建任何控件。
    """

    # 状态 / 进度
    state_changed = Signal(object, object)        # (new_state, old_state)
    progress_changed = Signal(int, int)           # (current 1-based, total)
    preparing_progress = Signal(int, int)         # (done, total) 预合成进度
    countdown_tick = Signal(int)                  # 3 / 2 / 1 / 0
    writing_tick = Signal(float, float)          # (remaining, total) 书写倒计时
    word_changed = Signal(object, int)            # (WordItem, index 1-based)
    word_repeat_changed = Signal(int, int)        # (current_repeat, total_repeat)

    # 结束 / 异常
    finished = Signal(object)                     # result dict
    aborted = Signal()
    info = Signal(str)                            # 信息 / 警告（如某词走离线）
    fallback_saying = Signal(object, int)         # (WordItem, index) 正在用离线引擎

    def __init__(self, tts, player, fallback, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tts = tts
        self._player = player
        self._fallback = fallback

        self.state: EngineState = EngineState.IDLE
        self._total = 0
        self._pos = 0
        self._repeat_index = 1
        self._cfg: Optional[PlayConfig] = None
        self._subject = "chinese"

        # 预合成结果
        self._items: list[WordItem] = []
        self._order: list[int] = []
        self._ordered_items: list[WordItem] = []
        self._voice_map: dict[str, str] = {}
        self._prepared: dict[str, str] = {}
        self._failed: set[str] = set()
        self._prep_done = 0
        self._prep_total = 0

        # 播放 / 暂停追踪
        self._awaiting_speech = False
        self._using_fallback = False
        self._pre_pause: Optional[EngineState] = None

        # 听写信息播报追踪
        self._playing_announce = False
        self._playing_end_announce = False

        # 计时器
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_n = 0

        self._gap_timer = QTimer(self)
        self._gap_timer.setInterval(100)
        self._gap_timer.timeout.connect(self._on_gap_tick)
        self._gap_total = 0.0
        self._gap_elapsed = 0.0

        self._write_timer = QTimer(self)
        self._write_timer.setInterval(100)
        self._write_timer.timeout.connect(self._on_write_tick)
        self._write_total = 0.0
        self._write_elapsed = 0.0

        # 提示音
        self._beep_path: Optional[str] = self._ensure_beep()

        # 服务信号连接
        self._tts.prepared.connect(self._on_prepared)
        self._tts.failed.connect(self._on_prepared_failed)
        self._tts.progress.connect(self._on_prepare_progress)
        self._tts.single_ready.connect(self._on_single_ready)
        self._tts.single_failed.connect(self._on_single_failed)
        self._player.finished.connect(self._on_speech_finished)
        self._fallback.said_finished.connect(self._on_speech_finished)

    # ------------------------------------------------------------------ 提示音
    @staticmethod
    def _ensure_beep() -> Optional[str]:
        """确保提示音 wav 存在；失败返回 None（提示音静默降级）。"""
        try:
            assets = DATA_DIR / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            bp = assets / "beep.wav"
            if not bp.exists():
                make_beep_wav(bp)
            return str(bp)
        except Exception as exc:  # noqa: BLE001
            logger.warning("生成提示音失败，倒计时/结束提示音将静默：%s", exc)
            return None

    def _play_beep(self) -> None:
        if self._beep_path and Path(self._beep_path).exists():
            # 不设置 _awaiting_speech，结束信号会被 _on_speech_finished 忽略
            self._player.play_file(self._beep_path)

    # ------------------------------------------------------------------ 生命周期
    def start(self, wordlist: WordList, cfg: PlayConfig) -> None:
        """开始一场听写。

        ``wordlist`` 提供词条；``cfg`` 提供全部报读参数与已解析音色。
        只统计启用词条（``enabled`` 为 True）。
        """
        enabled = [it for it in wordlist.items if it.enabled]
        if not enabled:
            self.info.emit("词表里没有启用词条，无法开始听写。")
            return

        self._items = enabled
        self._cfg = cfg
        self._subject = cfg.subject

        # 乱序：仅作用于本次播放序列，不改动词表存储顺序
        indices = list(range(len(enabled)))
        if cfg.shuffle:
            rng = random.Random(cfg.seed)
            rng.shuffle(indices)
        self._order = indices
        self._ordered_items = [enabled[i] for i in indices]
        self._total = len(enabled)
        self._pos = 0

        # 男女声混读：按播放位置轮换音色（规范 §F2.7 复刻）
        self._voice_map = {}
        n = len(cfg.voices) or 1
        for p, it in enumerate(self._ordered_items):
            self._voice_map[it.id] = cfg.voices[p % n] if cfg.voices else ""

        self._prepared = {}
        self._failed = set()
        self._prep_done = 0
        self._prep_total = self._total
        self._awaiting_speech = False

        self._set_state(EngineState.PREPARING)
        self.preparing_progress.emit(0, self._total)
        self.progress_changed.emit(1, self._total)

        params = SpeakParams(rate=cfg.rate, volume=cfg.volume, pitch=cfg.pitch)
        # prepare 内部按 voice_of 决定每条音色（含混读轮换）
        self._tts.prepare(
            self._ordered_items,
            lambda it: self._voice_map.get(it.id, ""),
            params,
            cfg.concurrency,
        )

    def pause(self) -> None:
        """暂停：冻结播放器与所有计时器，记录暂停前的状态。"""
        if self.state not in (
            EngineState.SPEAKING, EngineState.INNER_GAP,
            EngineState.WRITING, EngineState.COUNTDOWN,
        ):
            return
        self._pre_pause = self.state
        if self.state == EngineState.SPEAKING and not self._using_fallback:
            self._player.pause()
        self._gap_timer.stop()
        self._write_timer.stop()
        self._countdown_timer.stop()
        self._set_state(EngineState.PAUSED)

    def resume(self) -> None:
        """从 PAUSED 原地恢复（倒计时从剩余秒数接着走）。"""
        if self.state != EngineState.PAUSED:
            return
        prev = self._pre_pause
        if prev == EngineState.SPEAKING:
            if self._using_fallback:
                # 离线引擎无法中途暂停，重新播报当前遍
                self._speak_repeat()
            else:
                self._player.resume()
                self._set_state(EngineState.SPEAKING)
        elif prev == EngineState.INNER_GAP:
            self._set_state(EngineState.INNER_GAP)
            self._gap_timer.start()
        elif prev == EngineState.WRITING:
            self._set_state(EngineState.WRITING)
            self._write_timer.start()
        elif prev == EngineState.COUNTDOWN:
            self._set_state(EngineState.COUNTDOWN)
            self._countdown_timer.start()

    def stop(self) -> None:
        """中止：复位状态机，回到 IDLE。"""
        self._stop_active()
        self._reset_fields()
        self._set_state(EngineState.IDLE)
        self.aborted.emit()

    # 控制条 / 快捷键
    def replay_current(self) -> None:
        """重读本题（R）：从第一遍重新报读当前词。"""
        if self.state not in (
            EngineState.SPEAKING, EngineState.INNER_GAP, EngineState.WRITING,
        ):
            return
        self._stop_active()
        self._repeat_index = 1
        self._speak_repeat()

    def next(self) -> None:
        """下一个 / 跳过：结束当前词，直接进入下一词。"""
        if self.state not in (
            EngineState.SPEAKING, EngineState.INNER_GAP, EngineState.WRITING,
        ):
            return
        self._stop_active()
        self._advance()

    def prev(self) -> None:
        """上一个（←）：回退到上一词重新报读。"""
        if self.state not in (
            EngineState.SPEAKING, EngineState.INNER_GAP, EngineState.WRITING,
        ):
            return
        self._stop_active()
        if self._pos > 0:
            self._pos -= 1
        self._begin_word()

    # ------------------------------------------------------------------ 预合成回调
    def _on_prepared(self, item_id: str, path: str) -> None:
        self._prepared[item_id] = path

    def _on_prepared_failed(self, item_id: str, err: str) -> None:
        self._failed.add(item_id)
        text = self._item_text(item_id)
        self.info.emit(f"「{text}」合成失败，将改用离线引擎播报。")

    def _on_prepare_progress(self, done: int, total: int) -> None:
        self.preparing_progress.emit(done, total)
        if self.state == EngineState.PREPARING and done >= total:
            if self._cfg and getattr(self._cfg, "announce", True):
                self._enter_announcing()
            else:
                self._enter_countdown()

    # ------------------------------------------------------------------ 听写信息播报
    def _enter_announcing(self) -> None:
        """开场播报：词数 / 遍数 / 书写时间 / 确认音量提示，随后进入倒计时。"""
        if self.state != EngineState.PREPARING:
            return
        self._set_state(EngineState.ANNOUNCING)
        n = self._total
        rep = self._cfg.repeat if self._cfg else 2
        iv = self._cfg.interval if self._cfg else 10
        inner = self._cfg.inner_pause if self._cfg else 1.5
        est = estimate_dictation_minutes(n, rep, inner, iv)
        time_hint = f"预计约 {est} 分钟" if est >= 1 else "不到 1 分钟"
        text = (
            f"本次听写共 {n} 个词语，每个朗读 {rep} 遍，"
            f"每词书写 {iv:.0f} 秒，{time_hint}。"
            f"请确认音量，准备开始。"
        )
        voice = self._announce_voice()
        self._playing_announce = True
        self._tts.synthesize("__announce__", text, voice,
                             self._cfg.rate, self._cfg.volume, self._cfg.pitch)

    def _on_single_ready(self, request_id: str, path: str) -> None:
        """处理单条合成结果：开场/结束播报按状态播放，其余（试听等）由外部处理。"""
        if request_id == "__announce__":
            if self.state == EngineState.ANNOUNCING:
                self._awaiting_speech = True
                self._player.play_file(path)
            return
        if request_id == "__end_announce__":
            if self.state != EngineState.IDLE:
                self._awaiting_speech = True
                self._player.play_file(path)
            return
        # 其它 request_id（试听 / 重听）不在此处处理

    def _on_single_failed(self, request_id: str, err: str) -> None:
        if request_id in ("__announce__", "__end_announce__"):
            self._playing_announce = False
            self._playing_end_announce = False
            # 开场播报失败不应阻塞听写：仍在播报态则直接进入倒计时
            if request_id == "__announce__" and self.state == EngineState.ANNOUNCING:
                self._enter_countdown()
            return
        # 其它（试听等）由外部处理

    # ------------------------------------------------------------------ 状态进入
    def _enter_countdown(self) -> None:
        # 预合成完成（PREPARING）或开场播报播完（ANNOUNCING）都应进入倒计时
        if self.state not in (EngineState.PREPARING, EngineState.ANNOUNCING):
            return
        self._set_state(EngineState.COUNTDOWN)
        self._countdown_n = 3
        self.countdown_tick.emit(3)
        if self._cfg and self._cfg.countdown_beep:
            self._play_beep()
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self) -> None:
        if self._countdown_n > 1:
            self._countdown_n -= 1
            self.countdown_tick.emit(self._countdown_n)
            if self._cfg and self._cfg.countdown_beep:
                self._play_beep()
        else:
            self._countdown_timer.stop()
            self.countdown_tick.emit(0)
            self._begin_word()

    def _begin_word(self) -> None:
        item = self._ordered_items[self._pos]
        self.progress_changed.emit(self._pos + 1, self._total)
        self.word_changed.emit(item, self._pos + 1)
        self._repeat_index = 1
        self._speak_repeat()

    def _speak_repeat(self) -> None:
        item = self._ordered_items[self._pos]
        self._set_state(EngineState.SPEAKING)
        rep = self._effective_repeat(item)
        self.word_repeat_changed.emit(self._repeat_index, rep)

        if self._cfg and self._cfg.word_beep:
            self._play_beep()

        path = self._prepared.get(item.id)
        if path and Path(path).exists():
            self._using_fallback = False

            def _play() -> None:
                self._awaiting_speech = True
                self._player.play_file(path)

            if self._cfg and self._cfg.word_beep:
                # 等提示音播完再报词，避免被截断
                QTimer.singleShot(160, _play)
            else:
                _play()
        else:
            # 离线降级：直接用语系统 TTS
            self._awaiting_speech = True
            self._using_fallback = True
            text = item.alias or item.text
            self.fallback_saying.emit(item, self._pos + 1)
            self._fallback.say(text, self._subject)

    def _on_speech_finished(self) -> None:
        if not self._awaiting_speech:
            return
        self._awaiting_speech = False
        if self._playing_announce:
            self._playing_announce = False
            self._enter_countdown()
            return
        if self._playing_end_announce:
            self._playing_end_announce = False
            return
        item = self._ordered_items[self._pos]
        rep = self._effective_repeat(item)
        if self._repeat_index < rep:
            self._enter_gap(self._cfg.inner_pause if self._cfg else 1.0)
        else:
            self._enter_writing(item)

    def _enter_gap(self, pause_sec: float) -> None:
        self._set_state(EngineState.INNER_GAP)
        self._gap_total = pause_sec
        self._gap_elapsed = 0.0
        self._gap_timer.start()

    def _on_gap_tick(self) -> None:
        self._gap_elapsed += 0.1
        if self._gap_elapsed >= self._gap_total:
            self._gap_timer.stop()
            self._repeat_index += 1
            self._speak_repeat()

    def _enter_writing(self, item: WordItem) -> None:
        self._set_state(EngineState.WRITING)
        iv = self._effective_interval(item)
        self._write_total = iv
        self._write_elapsed = 0.0
        self.writing_tick.emit(iv, iv)
        self._write_timer.start()

    def _on_write_tick(self) -> None:
        self._write_elapsed += 0.1
        rem = max(0.0, self._write_total - self._write_elapsed)
        self.writing_tick.emit(rem, self._write_total)
        if rem <= 0:
            self._write_timer.stop()
            self._advance()

    def _advance(self) -> None:
        if self._pos + 1 < self._total:
            self._pos += 1
            self._begin_word()
        elif self._cfg and self._cfg.loop:
            self._pos = 0
            self._begin_word()
        else:
            self._finish()

    def _finish(self) -> None:
        self._stop_active()
        if self._cfg and self._cfg.end_beep:
            self._play_beep()
        # 结束播报：本轮听写已完成
        if self._cfg and getattr(self._cfg, "announce", True):
            text = f"听写结束，本次共 {self._total} 个词语。"
            voice = self._announce_voice()
            self._playing_end_announce = True
            self._tts.synthesize("__end_announce__", text, voice,
                                 self._cfg.rate, self._cfg.volume, self._cfg.pitch)
        self._set_state(EngineState.FINISHED)
        result = {
            "subject": self._subject,
            "total": self._total,
            "words": [
                {"text": it.text, "alias": it.alias, "lang": it.lang}
                for it in self._ordered_items
            ],
        }
        self.finished.emit(result)

    # ------------------------------------------------------------------ 辅助
    def _announce_voice(self) -> str:
        """为中文播报挑选音色：优先中文音色，否则回退固定中文嗓音。

        英语听写时 ``cfg.voices`` 多为 ``en-US-*`` 等英文音色，用来念中文播报
        会读不出字、只剩数字，因此这里强制走中文音色。
        """
        for v in (self._cfg.voices if self._cfg else []) or []:
            if str(v).lower().startswith("zh-"):
                return v
        return _ANNOUNCE_VOICE

    def _stop_active(self) -> None:
        """停掉所有计时器与播放器，但保留进度字段。"""
        self._gap_timer.stop()
        self._write_timer.stop()
        self._countdown_timer.stop()
        self._player.stop()
        self._fallback.stop()
        self._awaiting_speech = False

    def _reset_fields(self) -> None:
        self._items = []
        self._order = []
        self._ordered_items = []
        self._voice_map = {}
        self._prepared = {}
        self._failed = set()
        self._prep_done = 0
        self._prep_total = 0
        self._pos = 0
        self._repeat_index = 1
        self._using_fallback = False
        self._pre_pause = None

    def _set_state(self, s: EngineState) -> None:
        old = self.state
        self.state = s
        self.state_changed.emit(s, old)

    def _effective_repeat(self, item: WordItem) -> int:
        if self._cfg is None:
            return 1
        return item.repeat if item.repeat else self._cfg.repeat

    def _effective_interval(self, item: WordItem) -> float:
        if self._cfg is None:
            return 0.0
        return item.interval if item.interval else self._cfg.interval

    def _item_text(self, item_id: str) -> str:
        for it in self._ordered_items:
            if it.id == item_id:
                return it.text
        return item_id

    def is_active(self) -> bool:
        """是否处于进行中的状态（用于退出/切换页面二次确认）。"""
        return self.state in (
            EngineState.PREPARING, EngineState.COUNTDOWN, EngineState.SPEAKING,
            EngineState.INNER_GAP, EngineState.WRITING,
        )

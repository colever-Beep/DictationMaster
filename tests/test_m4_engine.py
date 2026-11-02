"""M4 听写引擎单元测试：状态机流转、乱序、音色轮换、暂停恢复、完整跑通。

不依赖真实音频/网络：用轻量 Fake 服务驱动状态机，覆盖规范 §F3 的关键路径。
运行：pytest tests/test_m4_engine.py -q （offscreen 即可，需 conftest 提供的 app 夹具）
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from core.dictation_engine import (
    DictationEngine,
    EngineState,
    PlayConfig,
    make_beep_wav,
)
from data.models import WordItem, WordList


# ---------------------------------------------------------------------- 测试夹具
class FakeTTS(QObject):
    prepared = Signal(str, str)
    failed = Signal(str, str)
    progress = Signal(int, int)
    single_ready = Signal(str, str)
    single_failed = Signal(str, str)

    def prepare(self, items, voice_of, params, concurrency: int = 4) -> None:
        for i, it in enumerate(items):
            self.prepared.emit(it.id, f"fake://{it.id}")
            self.progress.emit(i + 1, len(items))

    def synthesize(self, rid, text, voice, rate, volume, pitch):
        # 测试默认关闭播报，此分支一般不触发；保留以便复用
        self.single_ready.emit(rid, f"fake://{rid}")


class FakeTTSFile(QObject):
    """预合成写到真实临时文件，覆盖「走播放器」分支。"""

    prepared = Signal(str, str)
    failed = Signal(str, str)
    progress = Signal(int, int)
    single_ready = Signal(str, str)
    single_failed = Signal(str, str)

    def __init__(self, base: Path) -> None:
        super().__init__()
        self._base = base

    def prepare(self, items, voice_of, params, concurrency: int = 4) -> None:
        for i, it in enumerate(items):
            p = self._base / f"{it.id}.mp3"
            p.write_bytes(b"mp3")
            self.prepared.emit(it.id, str(p))
            self.progress.emit(i + 1, len(items))

    def synthesize(self, rid, text, voice, rate, volume, pitch):
        self.single_ready.emit(rid, f"fake://{rid}")


class FakePlayer(QObject):
    finished = Signal()
    source_changed = Signal(str)

    def play_file(self, path: str) -> None:
        self.path = path

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def stop(self) -> None:
        pass


class FakeFallback(QObject):
    said_finished = Signal()

    def say(self, text: str, subject: str) -> None:
        self.last_text = text

    def stop(self) -> None:
        pass


def _make_wl(n: int, subject: str = "chinese",
             repeat: list[int | None] | None = None) -> WordList:
    items = []
    for i in range(n):
        r = repeat[i] if repeat else None
        items.append(WordItem(id=f"it{i}", text=f"词{i}", lang="zh",
                              enabled=True, repeat=r))
    return WordList(id="wl1", name="测试", subject=subject, items=items)


# ---------------------------------------------------------------------- 单元测试
def test_engine_initial_state():
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    assert e.state == EngineState.IDLE


def test_shuffle_deterministic():
    wl = _make_wl(5)
    cfg = PlayConfig(subject="chinese", shuffle=True, seed=123, announce=False)
    e1 = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e1.start(wl, cfg)
    order1 = list(e1._order)
    e1.stop()

    e2 = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e2.start(wl, cfg)
    order2 = list(e2._order)
    e2.stop()
    assert order1 == order2
    assert sorted(order1) == list(range(5))

    # 不随机 => 保持原顺序
    e3 = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e3.start(wl, PlayConfig(subject="chinese", shuffle=False, announce=False))
    assert list(e3._order) == list(range(5))
    e3.stop()


def test_voice_rotation():
    wl = _make_wl(3)
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e.start(wl, PlayConfig(subject="chinese", voices=["A", "B"], announce=False))
    mapped = [e._voice_map[it.id] for it in e._ordered_items]
    assert mapped == ["A", "B", "A"]
    e.stop()


def test_effective_repeat_interval():
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e._cfg = PlayConfig(repeat=2, interval=10, inner_pause=1.5)
    overridden = WordItem(id="x", text="t", repeat=3, interval=5)
    assert e._effective_repeat(overridden) == 3
    assert e._effective_interval(overridden) == 5
    plain = WordItem(id="y", text="t2")
    assert e._effective_repeat(plain) == 2
    assert e._effective_interval(plain) == 10


def test_announce_voice_is_chinese_for_english_subject():
    """英文听写时开场播报文本仍是中文，音色必须中文，否则只剩数字乱读。"""
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    e._cfg = PlayConfig(subject="english", voices=["en-US-AriaNeural"])
    assert e._announce_voice().startswith("zh-")

    e._cfg = PlayConfig(subject="chinese", voices=["zh-CN-YunxiNeural"])
    assert e._announce_voice() == "zh-CN-YunxiNeural"


def test_announce_flow_reaches_countdown(app):
    """开场播报播放完毕后必须进入倒计时，不能卡在 ANNOUNCING。"""
    tts, player, fb = FakeTTS(), FakePlayer(), FakeFallback()
    e = DictationEngine(tts, player, fb)
    states: list[EngineState] = []
    e.state_changed.connect(lambda n, o: states.append(n))
    # 进入 ANNOUNCING 后模拟「播报播完」
    e.state_changed.connect(
        lambda n, o: QTimer.singleShot(10, player.finished.emit)
        if n == EngineState.ANNOUNCING else None)

    wl = _make_wl(1)
    cfg = PlayConfig(subject="chinese", repeat=1, interval=10, inner_pause=0.1,
                     countdown_beep=False, announce=True,
                     voices=["zh-CN-XiaoxiaoNeural"])
    e.start(wl, cfg)
    for _ in range(300):
        app.processEvents()
        if EngineState.COUNTDOWN in states:
            break
        time.sleep(0.01)
    assert EngineState.ANNOUNCING in states
    assert EngineState.COUNTDOWN in states, "播报结束后应进入倒计时"
    e.stop()


def test_make_beep_wav(tmp_path):
    p = tmp_path / "beep.wav"
    make_beep_wav(p)
    assert p.exists() and p.stat().st_size > 44  # 至少含 WAV 头


def test_speaking_player_branch(tmp_path):
    """验证「缓存命中 -> 走播放器 -> 播放完成 -> 进入书写」分支。"""
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    it = WordItem(id="x", text="词", enabled=True)
    e._cfg = PlayConfig(subject="chinese", repeat=1, interval=1,
                        inner_pause=1, word_beep=False)
    e._ordered_items = [it]
    e._pos = 0
    e._prepared = {"x": str(f)}
    e._speak_repeat()
    assert e.state == EngineState.SPEAKING
    e._player.finished.emit()
    assert e.state == EngineState.WRITING
    e.stop()


def _drive(e, player, fb, app, timeout_iter: int = 800):
    """通用驱动：SPEAKING 后自动结束音频；离线时自动结束；泵事件循环直至 FINISHED。"""
    def on_state(n):
        if n == EngineState.SPEAKING:
            QTimer.singleShot(10, player.finished.emit)

    e.state_changed.connect(on_state)
    e.fallback_saying.connect(
        lambda *a: QTimer.singleShot(10, fb.said_finished.emit))
    for _ in range(timeout_iter):
        app.processEvents()
        if e.state == EngineState.FINISHED:
            break
        time.sleep(0.01)


def test_full_run_to_finished(app):
    tts, player, fb = FakeTTS(), FakePlayer(), FakeFallback()
    e = DictationEngine(tts, player, fb)
    states: list[EngineState] = []
    e.state_changed.connect(lambda n, o: states.append(n))
    result: dict = {}
    e.finished.connect(lambda r: result.update(r))

    wl = _make_wl(3)
    cfg = PlayConfig(subject="chinese", repeat=1, interval=0.1, inner_pause=0.1,
                     shuffle=False, loop=False, countdown_beep=False,
                     end_beep=False, word_beep=False, announce=False)
    e.start(wl, cfg)
    _drive(e, player, fb, app)
    assert e.state == EngineState.FINISHED
    assert result.get("total") == 3
    assert EngineState.PREPARING in states
    assert EngineState.COUNTDOWN in states
    assert EngineState.WRITING in states
    assert EngineState.SPEAKING in states


def test_full_run_player_branch(app, tmp_path):
    """走真实文件 + 播放器分支的完整跑通。"""
    base = tmp_path / "cache"
    base.mkdir()
    tts, player, fb = FakeTTSFile(base), FakePlayer(), FakeFallback()
    e = DictationEngine(tts, player, fb)
    result: dict = {}
    e.finished.connect(lambda r: result.update(r))

    wl = _make_wl(2)
    cfg = PlayConfig(subject="chinese", repeat=2, interval=0.1, inner_pause=0.1,
                     shuffle=False, loop=False, countdown_beep=False,
                     end_beep=False, word_beep=False, announce=False)
    e.start(wl, cfg)
    _drive(e, player, fb, app)
    assert e.state == EngineState.FINISHED
    assert result.get("total") == 2


def test_pause_resume_flow(app):
    tts, player, fb = FakeTTS(), FakePlayer(), FakeFallback()
    e = DictationEngine(tts, player, fb)
    saw_writing: list[bool] = []

    def on_state(n):
        if n == EngineState.SPEAKING:
            QTimer.singleShot(10, player.finished.emit)
        if n == EngineState.WRITING and not saw_writing:
            saw_writing.append(True)
            e.pause()
            QTimer.singleShot(60, e.resume)

    e.state_changed.connect(on_state)
    e.fallback_saying.connect(
        lambda *a: QTimer.singleShot(10, fb.said_finished.emit))

    wl = _make_wl(2)
    cfg = PlayConfig(subject="chinese", repeat=1, interval=0.2, inner_pause=0.1,
                     shuffle=False, loop=False, countdown_beep=False,
                     end_beep=False, word_beep=False, announce=False)
    e.start(wl, cfg)
    _drive(e, player, fb, app)
    assert e.state == EngineState.FINISHED
    assert saw_writing, "应当经历至少一次书写阶段"


def test_stop_returns_idle(app):
    tts, player, fb = FakeTTS(), FakePlayer(), FakeFallback()
    e = DictationEngine(tts, player, fb)
    wl = _make_wl(3)
    e.start(wl, PlayConfig(subject="chinese", countdown_beep=False, announce=False))
    # 立即中止
    e.stop()
    assert e.state == EngineState.IDLE


def test_empty_wordlist_no_crash(app):
    e = DictationEngine(FakeTTS(), FakePlayer(), FakeFallback())
    wl = WordList(id="e", name="空", subject="chinese", items=[])
    # 不应进入 PREPARING / 不应抛异常
    e.start(wl, PlayConfig(subject="chinese"))
    assert e.state == EngineState.IDLE

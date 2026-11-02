"""TTS 引擎切换 + 听写信息播报 相关测试。

覆盖：
- 缓存 key 按引擎区分（edge 兼容历史格式），路径后缀随引擎变化；
- TTSService 引擎路由：默认 edge，set_engine 切换并触发 engine_changed，
  kokoro 走 .wav、edge 走 .mp3；
- 设置项 kokoro_enabled / announce_enabled 存在且类型正确；
- ParamCard.build_config 把 announce 注入 PlayConfig；
- DictationEngine 在 announce 开启时进入 ANNOUNCING 并请求开场播报，
  关闭时直接进入倒计时。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def test_cache_key_engine_aware():
    from core.cache import cache_key, cache_path

    legacy = cache_key("苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz")
    edge = cache_key("苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz", "edge")
    kokoro = cache_key("苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz", "kokoro")

    # edge 必须复用历史 key 格式（保持旧缓存有效）
    assert edge == legacy
    assert len(edge) == 40 and len(kokoro) == 40
    assert edge != kokoro
    # 路径后缀随引擎变化
    assert str(cache_path(edge, suffix=".mp3")).endswith(".mp3")
    assert str(cache_path(kokoro, suffix=".wav")).endswith(".wav")


def test_tts_service_engine_routing(app, tmp_path, monkeypatch):
    from core.tts_service import TTSService

    called: dict[str, int] = {}

    async def fake_edge(self, *, text, voice, rate, volume, pitch, proxy, out_path):
        called["edge"] = called.get("edge", 0) + 1
        Path(out_path).write_bytes(b"EDGE")

    async def fake_kokoro(self, *, text, voice, rate, volume, pitch, proxy, out_path):
        called["kokoro"] = called.get("kokoro", 0) + 1
        Path(out_path).write_bytes(b"KOKORO")

    monkeypatch.setattr("core.tts_backend.EdgeBackend.synth", fake_edge)
    monkeypatch.setattr("core.tts_backend.KokoroBackend.synth", fake_kokoro)

    svc = TTSService(cache_dir=tmp_path / "c")
    try:
        assert svc.engine() == "edge"
        changed = []
        svc.engine_changed.connect(changed.append)
        ready: dict[str, str] = {}
        svc.single_ready.connect(lambda rid, p: ready.__setitem__(rid, p))

        # r1 用默认 edge 引擎先合成完成
        svc.synthesize("r1", "苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz")
        for _ in range(50):
            app.processEvents()
            if "r1" in ready:
                break
            time.sleep(0.05)
        assert "r1" in ready and ready["r1"].endswith(".mp3")

        # 再切到 kokoro 合成 r2
        svc.set_engine("kokoro")
        assert svc.engine() == "kokoro"
        assert "kokoro" in changed
        svc.synthesize("r2", "苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz")
        for _ in range(50):
            app.processEvents()
            if "r2" in ready:
                break
            time.sleep(0.05)
        assert "r2" in ready and ready["r2"].endswith(".wav")

        assert called.get("edge") == 1, called
        assert called.get("kokoro") == 1, called
    finally:
        svc.shutdown()


def test_engine_config_items_exist():
    from app_config import cfg

    assert hasattr(cfg, "kokoro_enabled")
    assert hasattr(cfg, "announce_enabled")
    # 默认：在线引擎、开启播报
    assert cfg.kokoro_enabled.value in (True, False)
    assert cfg.announce_enabled.value in (True, False)


def test_param_card_injects_announce(app):
    from app_config import cfg
    from ui.widgets.param_card import ParamCard

    card = ParamCard()
    cfg.announce_enabled.value = False
    pc = card.build_config("chinese")
    assert pc.announce is False
    cfg.announce_enabled.value = True
    pc = card.build_config("chinese")
    assert pc.announce is True


def test_dictation_announce_toggle(app, tmp_path):
    from core.audio_player import AudioPlayer
    from core.dictation_engine import DictationEngine, EngineState, PlayConfig
    from core.fallback_tts import FallbackTTS
    from data.models import WordItem, WordList

    class FakeTTS(QObject):
        prepared = Signal(str, str)
        failed = Signal(str, str)
        progress = Signal(int, int)
        single_ready = Signal(str, str)
        single_failed = Signal(str, str)
        engine_changed = Signal(str)

        def __init__(self):
            super().__init__()
            self.requests: list[str] = []

        def prepare(self, items, voice_of, params, concurrency):
            for it in items:
                self.prepared.emit(it.id, f"fake/{it.id}.mp3")
            self.progress.emit(len(items), len(items))

        def synthesize(self, rid, text, voice, rate, volume, pitch):
            self.requests.append(rid)
            self.single_ready.emit(rid, "fake/ann.mp3")

        def set_engine(self, name):
            pass

        def cache_dir(self):
            return "."

        def shutdown(self):
            pass

    wl = WordList(
        id="w", name="t", subject="chinese",
        items=[WordItem(id="1", text="苹果", lang="zh")],
    )
    player = AudioPlayer()
    fallback = FallbackTTS()

    # 开启播报：应进入 ANNOUNCING 并请求开场播报
    tts_on = FakeTTS()
    eng_on = DictationEngine(tts_on, player, fallback)
    states_on: list[str] = []
    eng_on.state_changed.connect(lambda n, o: states_on.append(n))
    eng_on.start(wl, PlayConfig(subject="chinese", announce=True,
                                voices=["zh-CN-XiaoxiaoNeural"]))
    for _ in range(20):
        app.processEvents()
        if EngineState.ANNOUNCING in states_on:
            break
        time.sleep(0.05)
    assert EngineState.ANNOUNCING in states_on
    assert "__announce__" in tts_on.requests

    # 关闭播报：应直接进入倒计时，不请求开场播报
    tts_off = FakeTTS()
    eng_off = DictationEngine(tts_off, player, fallback)
    states_off: list[str] = []
    eng_off.state_changed.connect(lambda n, o: states_off.append(n))
    eng_off.start(wl, PlayConfig(subject="chinese", announce=False,
                                 voices=["zh-CN-XiaoxiaoNeural"]))
    for _ in range(20):
        app.processEvents()
        if EngineState.COUNTDOWN in states_off:
            break
        time.sleep(0.05)
    assert EngineState.COUNTDOWN in states_off
    assert "__announce__" not in tts_off.requests

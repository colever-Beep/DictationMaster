"""无显示器冒烟测试：验证配置、路径、缓存与页面可构建。

运行：pytest tests/  （需安装 pytest，且环境为 offscreen 或已装显示器）
"""

from __future__ import annotations

import pytest


def test_config_loads(app):
    from app_config import init_config, cfg

    init_config()
    assert cfg.theme.value is not None
    assert cfg.repeat.value == 2
    assert cfg.cache_dir.value


def test_paths_exist():
    from core import paths

    for p in (
        paths.APP_DATA,
        paths.CACHE_DIR,
        paths.LOGS_DIR,
        paths.WORDLISTS_DIR,
        paths.DATA_DIR,
    ):
        assert p.exists(), f"缺失目录: {p}"


def test_cache_key_stable():
    from core.cache import cache_key

    a = cache_key("苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz")
    b = cache_key("苹果", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz")
    assert a == b and len(a) == 40


def test_pages_build(app):
    from ui.pages.dictation_page import DictationPage
    from ui.pages.setting_page import SettingPage
    from ui.pages.about_page import AboutPage

    for cls in (DictationPage, SettingPage, AboutPage):
        w = cls()
        assert w is not None


def test_main_window_build(app):
    from core.services import Services
    from ui.main_window import MainWindow

    services = Services()
    try:
        w = MainWindow(services)
        assert w is not None
    finally:
        services.shutdown()


def test_tts_service_construct_shutdown(app, tmp_path):
    from core.tts_service import TTSService

    svc = TTSService(cache_dir=tmp_path / "cache")
    try:
        assert svc._thread.isRunning()
    finally:
        svc.shutdown()
        assert not svc._thread.isRunning()


def test_audio_player_construct(app):
    from core.audio_player import AudioPlayer

    p = AudioPlayer()
    p.set_volume(0.5)
    p.stop()
    assert p is not None


def test_fallback_tts_construct(app):
    from core.fallback_tts import FallbackTTS

    f = FallbackTTS()
    assert f is not None
    # 不调用 say；仅验证引擎对象可用


def test_voice_builtin_fallback():
    from core.voice import VoiceManager, builtin_voices

    vm = VoiceManager()
    # 未联网也应至少有一份内置兜底列表
    assert len(vm.current()) == len(builtin_voices())
    assert any(v.short_name.startswith("zh-CN") for v in vm.current())
    assert any(v.short_name.startswith("en-US") for v in vm.current())


def test_services_construct(app):
    from core.services import Services

    s = Services()
    try:
        assert s.tts is not None
        assert s.player is not None
        assert s.fallback is not None
        assert s.voices is not None
    finally:
        s.shutdown()


def test_edge_tts_volume_does_not_mute_player(app):
    from types import SimpleNamespace

    from core.services import Services

    s = Services()
    try:
        config = SimpleNamespace(
            proxy=SimpleNamespace(value=""),
            volume=SimpleNamespace(value="+0%"),
        )
        s.apply_config(config)
        assert s.player._output.volume() == pytest.approx(0.8)
    finally:
        s.shutdown()


def test_dictation_page_with_services(app):
    from core.services import Services
    from ui.pages.dictation_page import DictationPage

    services = Services()
    try:
        w = DictationPage(services)
        assert w is not None
    finally:
        services.shutdown()


def test_dictation_page_placeholder(app):
    from ui.pages.dictation_page import DictationPage

    # 无服务时应为占位构建，不依赖任何后台资源
    w = DictationPage()
    assert w is not None


def test_tts_service_honors_cache_dir(app, tmp_path):
    """验证 TTSService 写入的是注入的缓存目录（而非全局 CACHE_DIR）。"""
    from core.cache import cache_key
    from core.tts_service import TTSService

    cache_dir = tmp_path / "mycache"
    svc = TTSService(cache_dir=cache_dir)
    try:
        text, voice, rate, vol, pitch = "测试", "zh-CN-XiaoxiaoNeural", "-10%", "+0%", "+0Hz"
        key = cache_key(text, voice, rate, vol, pitch)
        (cache_dir / f"{key}.mp3").write_bytes(b"SEED")
        (cache_dir / f"{key}.mp3").chmod(0o644)

        ready: dict[str, str] = {}
        svc.single_ready.connect(lambda rid, p: ready.__setitem__(rid, p))
        svc.single_failed.connect(lambda rid, e: ready.__setitem__(rid, f"FAIL:{e}"))
        svc.synthesize("c", text, voice, rate, vol, pitch)
        for _ in range(40):
            app.processEvents()
            if "c" in ready:
                break
            import time
            time.sleep(0.05)
        assert "c" in ready and not ready["c"].startswith("FAIL")
        # 返回路径必须落在注入的缓存目录内
        assert str(cache_dir) in ready["c"]
    finally:
        svc.shutdown()

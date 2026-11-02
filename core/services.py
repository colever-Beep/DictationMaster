"""服务容器：聚合语音层各组件，供 UI 与后续听写引擎（M4）复用。

本模块属于 ``core`` 层，**绝不** import 任何 ``ui`` 模块；UI 通过 MainWindow 拿到
``Services`` 实例后注入各页面。集中创建可保证全局只有一份后台 loop 线程与播放器。
"""

from __future__ import annotations

import logging

from core.audio_player import AudioPlayer
from core.fallback_tts import FallbackTTS
from core.tts_service import TTSService
from core.voice import VoiceManager

logger = logging.getLogger(__name__)


class Services:
    """应用级服务聚合。"""

    def __init__(self) -> None:
        # 缓存目录在各组件创建前确保存在
        from app_config import cfg

        self._app_cfg = cfg  # 保存对真实配置单例的引用，apply_config 时也能读到
        self.tts = TTSService(cache_dir=cfg.cache_dir.value)
        # 按配置选择 TTS 引擎（在线 Edge / 离线 Kokoro），并随设置实时切换
        self.tts.set_engine("kokoro" if cfg.kokoro_enabled.value else "edge")
        cfg.kokoro_enabled.valueChanged.connect(
            lambda v: self.tts.set_engine("kokoro" if v else "edge"))
        self.player = AudioPlayer()
        self.fallback = FallbackTTS()
        self.voices = VoiceManager()

    def apply_config(self, cfg) -> None:
        """把代理等配置推送到各服务。"""
        self.tts.set_proxy(cfg.proxy.value)
        self.tts.set_engine(
            "kokoro" if self._app_cfg.kokoro_enabled.value else "edge")
        self.voices.set_proxy(cfg.proxy.value)

    def refresh_voices(self, force: bool = False) -> None:
        """拉取音色列表（联网失败自动回退内置）。"""
        self.voices.fetch(force=force)

    def shutdown(self) -> None:
        """应用退出时清理后台资源。"""
        try:
            self.tts.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TTSService 关闭异常：%s", exc)
        try:
            self.player.stop()
            self.fallback.stop()
        except Exception:  # noqa: BLE001
            pass

"""音频播放封装：基于 ``QMediaPlayer`` + ``QAudioOutput``，事件驱动判定播放完成。

对应规范 §4.3 / §8.3：

- ``QMediaPlayer`` 与 ``QAudioOutput`` **必须作为实例属性持有**，否则被 GC 回收会导致静默无声。
- 播放完成判定一律用 ``mediaStatusChanged == EndOfMedia``，不要用定时器猜时长。
- 换源前先 ``stop()`` 再 ``setSource()``，避免偶发丢失首次播放状态。
- 所有方法均由 UI / 状态机在主线程调用，不做阻塞操作。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

logger = logging.getLogger(__name__)


class AudioPlayer(QObject):
    """单文件顺序播放器。"""

    finished = Signal()                 # 单个音频自然播完
    error = Signal(str)                 # 错误信息
    source_changed = Signal(str)        # 当前播放源路径（用于 UI 联动）

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 必须持有实例引用，否则被 GC 回收导致静默无声音
        self._output = QAudioOutput(self)
        self._output.setVolume(0.8)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._current_path: str = ""

    def play_file(self, path: str) -> None:
        """播放本地音频文件（mp3）。会自动停掉上一段再换源。"""
        self._current_path = path
        self._player.stop()                              # 换源前先停
        self._player.setSource(QUrl.fromLocalFile(path))
        self.source_changed.emit(path)
        self._player.play()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_volume(self, value: float) -> None:
        """设置音量，取值范围 0.0 ~ 1.0（线性）。"""
        self._output.setVolume(max(0.0, min(1.0, value)))

    def pause(self) -> None:
        self._player.pause()

    def resume(self) -> None:
        if self._current_path:
            self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self._current_path = ""

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()

    def _on_error(self, code: QMediaPlayer.Error, msg: str) -> None:
        # errorOccurred 异步上报，落日志并转交上层
        logger.error("音频播放错误 %s: %s", code, msg)
        self.error.emit(f"{code}: {msg}")

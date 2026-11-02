"""Edge-TTS 听写引擎：音频生成（后台线程）+ 顺序播放（主线程）。"""
import os
import asyncio
import tempfile
import shutil

import edge_tts
from PySide6.QtCore import QThread, Signal, QObject, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


# ----------------------------- 音频生成线程 -----------------------------
class TTSGenerator(QThread):
    """把词库批量生成 mp3 临时文件，避免朗读时网络抖动。"""
    progress = Signal(int, int, str)   # 当前, 总数, 当前词
    done = Signal(list)                # [(path, word_index), ...]
    errored = Signal(str)

    def __init__(self, words, voice, rate_str, pitch_str, repetitions):
        super().__init__()
        self.words = words
        self.voice = voice
        self.rate_str = rate_str
        self.pitch_str = pitch_str
        self.repetitions = repetitions
        self.tmpdir = tempfile.mkdtemp(prefix="tingxie_")

    def run(self):
        try:
            asyncio.run(self._generate())
        except Exception as e:  # noqa
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.errored.emit(f"生成音频失败：{e}")

    async def _generate(self):
        words = [w for w in self.words if w.strip()]
        reps = max(1, self.repetitions)
        total = len(words) * reps
        cur = 0
        segments = []
        for wi, word in enumerate(words):
            text = word.strip()
            for r in range(reps):
                cur += 1
                path = os.path.join(self.tmpdir, f"w{wi}_r{r}.mp3")
                comm = edge_tts.Communicate(
                    text=text, voice=self.voice,
                    rate=self.rate_str, pitch=self.pitch_str,
                )
                await comm.save(path)
                segments.append((path, wi))
                self.progress.emit(cur, total, text)
        self.done.emit(segments)


# ----------------------------- 顺序播放器 -----------------------------
class DictationPlayer(QObject):
    """按词序播放，支持 暂停/继续/停止/上一下一/单句预览。"""
    segment_started = Signal(int, int, int)  # seg_index, total, word_index
    word_changed = Signal(int, str)          # word_index, word_text（外部传入映射）
    gap_started = Signal(int, str)           # gap_ms, next_word_text
    finished = Signal()
    preview_ended = Signal()
    state_changed = Signal(str)              # "playing" / "paused" / "stopped"

    def __init__(self, word_list):
        super().__init__()
        self.word_list = word_list  # 原始词库（用于显示）
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self._on_status)

        self.segments = []        # [(path, word_index)]
        self.seg_index = 0
        self.paused = False
        self.stopped = True
        self.preview = False
        self._in_gap = False

        self.word_pause_ms = 3000
        self.rep_gap_ms = 1000

        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._play_next)

    # ---- 配置 ----
    def set_gaps(self, word_pause_ms, rep_gap_ms):
        self.word_pause_ms = word_pause_ms
        self.rep_gap_ms = rep_gap_ms

    def load(self, segments):
        self.segments = segments
        self.seg_index = 0

    # ---- 控制 ----
    def start(self):
        if not self.segments:
            return
        self.stopped = False
        self.paused = False
        self.preview = False
        self.seg_index = 0
        self._play_current()
        self.state_changed.emit("playing")

    def pause(self):
        if self.stopped or self.paused:
            return
        self.paused = True
        self.timer.stop()
        self.player.pause()
        self.state_changed.emit("paused")

    def resume(self):
        if not self.paused:
            return
        self.paused = False
        if self._in_gap:
            self.timer.start(self.word_pause_ms if self._next_is_new_word() else self.rep_gap_ms)
        else:
            self.player.play()
        self.state_changed.emit("playing")

    def stop(self):
        self.stopped = True
        self.paused = False
        self.preview = False
        self._in_gap = False
        self.timer.stop()
        self.player.stop()
        self.state_changed.emit("stopped")

    def next(self):
        if not self.segments:
            return
        if self.stopped and not self.paused:
            # 完全停止时：单句预览
            self.seg_index = min(self.seg_index + 1, len(self.segments) - 1)
            self._preview()
        else:
            self.timer.stop()
            self.player.stop()
            if self.seg_index < len(self.segments) - 1:
                self.seg_index += 1
                self.paused = False
                self._play_current()

    def prev(self):
        if not self.segments:
            return
        if self.stopped and not self.paused:
            self.seg_index = max(self.seg_index - 1, 0)
            self._preview()
        else:
            self.timer.stop()
            self.player.stop()
            if self.seg_index > 0:
                self.seg_index -= 1
                self.paused = False
                self._play_current()

    def _preview(self):
        self.preview = True
        self.stopped = False
        self.paused = False
        self._in_gap = False
        self._play_current()
        self.state_changed.emit("playing")

    # ---- 内部 ----
    def _play_current(self):
        if self.seg_index >= len(self.segments):
            self._finish()
            return
        path, wi = self.segments[self.seg_index]
        self._in_gap = False
        self.segment_started.emit(self.seg_index, len(self.segments), wi)
        self.word_changed.emit(wi, self.word_list[wi] if wi < len(self.word_list) else "")
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _on_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer as MP
        if status != MP.MediaStatus.EndOfMedia:
            return
        if self.paused or self.stopped:
            return
        self.seg_index += 1
        if self.preview:
            self.preview = False
            self.stopped = True
            self.state_changed.emit("stopped")
            self.preview_ended.emit()
            return
        if self.seg_index >= len(self.segments):
            self._finish()
            return
        self._in_gap = True
        gap = self.word_pause_ms if self._next_is_new_word() else self.rep_gap_ms
        next_wi = self.segments[self.seg_index][1]
        next_word = self.word_list[next_wi] if 0 <= next_wi < len(self.word_list) else ""
        self.gap_started.emit(gap, next_word)
        self.timer.start(gap)

    def _next_is_new_word(self):
        if self.seg_index >= len(self.segments):
            return True
        cur_wi = self.segments[self.seg_index - 1][1]
        nxt_wi = self.segments[self.seg_index][1]
        return nxt_wi != cur_wi

    def _play_next(self):
        self._in_gap = False
        self._play_current()

    def _finish(self):
        self.stopped = True
        self.paused = False
        self.state_changed.emit("stopped")
        self.finished.emit()

    def cleanup(self):
        try:
            self.timer.stop()
            self.player.stop()
        except Exception:
            pass
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    _tmpdir = None  # 由外部在生成后赋值，便于退出清理


# ----------------------------- 发音人列表获取 -----------------------------
class VoiceFetcher(QThread):
    done = Signal(list)     # [(ShortName, FriendlyName, Locale), ...]
    errored = Signal(str)

    def __init__(self, locale_filter="zh"):
        super().__init__()
        self.locale_filter = locale_filter

    def run(self):
        try:
            voices = asyncio.run(edge_tts.list_voices())
            result = []
            for v in voices:
                locale = v.get("Locale", "")
                if locale.startswith(self.locale_filter):
                    result.append((v["ShortName"], v.get("FriendlyName", v["ShortName"]), locale))
            self.done.emit(result)
        except Exception as e:  # noqa
            self.errored.emit(str(e))

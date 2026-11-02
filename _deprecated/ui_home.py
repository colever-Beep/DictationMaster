"""听写主界面：词库输入 + 播放控制 + 进度/倒计时。"""
import os
import shutil

from PySide6.QtCore import Qt, QTimer, QDateTime
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox

from qfluentwidgets import (
    CardWidget, PlainTextEdit, PushButton, PrimaryPushButton,
    ProgressBar, SubtitleLabel, BodyLabel, FluentIcon,
)
from core.tts import TTSGenerator, DictationPlayer
from core.config import Config


class HomeInterface(QWidget):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.words = []
        self.segments = []
        self.tmpdir = None
        self.generator = None
        self.player = None
        self._busy = False
        self._gap_end = 0

        self._build_ui()
        self._load_words()
        self._init_player()

    # ------------------------- UI -------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        root.addWidget(SubtitleLabel("听写"))
        root.addWidget(BodyLabel("基于 Edge-TTS 的听写练习，逐词朗读，可调节节奏"))

        # 词库卡片
        input_card = CardWidget()
        iv = QVBoxLayout(input_card)
        iv.setContentsMargins(16, 14, 16, 14)
        iv.setSpacing(10)
        iv.addWidget(BodyLabel("词库（每行一个词语，可含标点与句子）"))

        self.text_edit = PlainTextEdit()
        self.text_edit.setPlaceholderText(
            "例如：\n苹果\n香蕉\n天气预报\n一寸光阴一寸金\n"
            "（每行一个，点击「开始听写」后将逐词朗读）"
        )
        self.text_edit.setMinimumHeight(170)
        self.text_edit.textChanged.connect(self._on_text_changed)
        iv.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        self.import_btn = PushButton(text="导入文本", icon=FluentIcon.FOLDER)
        self.clear_btn = PushButton(text="清空", icon=FluentIcon.DELETE)
        self.save_btn = PushButton(text="保存词库", icon=FluentIcon.SAVE)
        self.import_btn.clicked.connect(self._import_text)
        self.clear_btn.clicked.connect(self._clear_text)
        self.save_btn.clicked.connect(self._save_text)
        for b in (self.import_btn, self.clear_btn, self.save_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        iv.addLayout(btn_row)
        root.addWidget(input_card)

        # 当前词显示
        self.word_card = CardWidget()
        wv = QVBoxLayout(self.word_card)
        wv.setContentsMargins(16, 18, 16, 18)
        wv.setSpacing(10)
        self.current_word = BodyLabel("准备就绪")
        self.current_word.setAlignment(Qt.AlignCenter)
        self.current_word.setStyleSheet("font-size: 30px; font-weight: 700;")
        wv.addWidget(self.current_word)

        self.progress = ProgressBar()
        self.progress.setRange(0, 100)
        wv.addWidget(self.progress)

        sub = QHBoxLayout()
        self.progress_label = BodyLabel("第 0 / 0 词")
        self.countdown_label = BodyLabel("")
        self.countdown_label.setAlignment(Qt.AlignRight)
        sub.addWidget(self.progress_label)
        sub.addStretch(1)
        sub.addWidget(self.countdown_label)
        wv.addLayout(sub)
        root.addWidget(self.word_card)

        # 控制按钮
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.start_btn = PrimaryPushButton(text="开始听写", icon=FluentIcon.PLAY)
        self.start_btn.clicked.connect(self._start)
        self.pause_btn = PushButton(text="暂停", icon=FluentIcon.PAUSE)
        self.next_btn = PushButton(text="下一个", icon=FluentIcon.DOWN)
        self.prev_btn = PushButton(text="上一个", icon=FluentIcon.UP)
        self.stop_btn = PushButton(text="停止", icon=FluentIcon.CANCEL)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn.clicked.connect(self._stop)
        self.prev_btn.clicked.connect(lambda: self.player.prev())
        self.next_btn.clicked.connect(lambda: self.player.next())
        for b in (self.start_btn, self.pause_btn, self.stop_btn, self.prev_btn, self.next_btn):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        root.addStretch(1)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(100)
        self._countdown_timer.timeout.connect(self._tick_countdown)

        self._update_controls("stopped")

    # ------------------------- 播放器 -------------------------
    def _init_player(self):
        self.player = DictationPlayer(self.words)
        self.player.set_gaps(
            int(self.config.word_pause * 1000),
            int(self.config.rep_gap * 1000),
        )
        self.player.segment_started.connect(self._on_segment_started)
        self.player.gap_started.connect(self._on_gap_started)
        self.player.finished.connect(self._on_finished)
        self.player.preview_ended.connect(self._on_preview_ended)
        self.player.state_changed.connect(self._update_controls)

    # ------------------------- 词库处理 -------------------------
    def _load_words(self):
        saved = self.config.words
        if saved:
            self.text_edit.setPlainText(saved)
        self._refresh_words()

    def _on_text_changed(self):
        self._refresh_words()

    def _refresh_words(self):
        raw = self.text_edit.toPlainText()
        self.words = [w.strip() for w in raw.splitlines() if w.strip()]
        if self.player is not None:
            self.player.word_list = self.words

    def _import_text(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入文本", self.config.download_dir(),
            "文本文件 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())
            self.config.words = self.text_edit.toPlainText()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _clear_text(self):
        self.text_edit.clear()
        self.config.words = ""

    def _save_text(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存词库", os.path.join(self.config.download_dir(), "词库.txt"),
            "文本文件 (*.txt)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_edit.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    # ------------------------- 开始/流程 -------------------------
    def _start(self):
        if self._busy:
            return
        self._refresh_words()
        if not self.words:
            QMessageBox.information(self, "提示", "请先在上方输入要听写的词语（每行一个）。")
            return

        self.config.words = self.text_edit.toPlainText()
        self.config.repetitions = self._reps()
        self.config.rate = self._rate()
        self.config.pitch = self._pitch()
        self.config.word_pause = self._word_pause()
        self.config.rep_gap = self._rep_gap()

        self._busy = True
        self._update_controls("generating")
        self.current_word.setText("正在生成音频…")
        self.countdown_label.setText("")

        self.generator = TTSGenerator(
            self.words, self.config.voice,
            self.config.rate_str(), self.config.pitch_str(),
            self.config.repetitions,
        )
        self.tmpdir = self.generator.tmpdir
        self.generator.progress.connect(self._on_gen_progress)
        self.generator.done.connect(self._on_gen_done)
        self.generator.errored.connect(self._on_gen_error)
        self.generator.finished.connect(lambda: setattr(self, "_busy", False))
        self.generator.start()

    def _on_gen_progress(self, cur, total, word):
        self.current_word.setText(f"生成中 {cur}/{total}：{word}")

    def _on_gen_done(self, segments):
        self.segments = segments
        self.player.word_list = self.words
        self.player.load(segments)
        self.player.set_gaps(
            int(self.config.word_pause * 1000),
            int(self.config.rep_gap * 1000),
        )
        self.player._tmpdir = self.tmpdir
        self.player.start()

    def _on_gen_error(self, msg):
        self._busy = False
        self.current_word.setText("生成失败")
        self._update_controls("stopped")
        QMessageBox.critical(self, "生成失败", msg)

    # ------------------------- 播放回调 -------------------------
    def _on_segment_started(self, seg, total, wi):
        self._countdown_timer.stop()
        self.countdown_label.setText("正在朗读…")
        word_count = len(self.words)
        if word_count:
            self.progress.setValue(int((wi + 1) / word_count * 100))
            self.progress_label.setText(f"第 {wi + 1} / {word_count} 词")
        if 0 <= wi < len(self.words):
            self.current_word.setText(self.words[wi])

    def _on_gap_started(self, gap_ms, next_word):
        if not self.config.countdown_enabled or not next_word:
            return
        self._gap_end = QDateTime.currentMSecsSinceEpoch() + gap_ms
        self._countdown_timer.start()

    def _tick_countdown(self):
        remain = self._gap_end - QDateTime.currentMSecsSinceEpoch()
        if remain <= 0:
            self._countdown_timer.stop()
            self.countdown_label.setText("")
            return
        self.countdown_label.setText(f"{remain / 1000.0:.1f} 秒后播放下一个")

    def _on_finished(self):
        self._countdown_timer.stop()
        self.current_word.setText("听写完成 🎉")
        self.countdown_label.setText("")
        self.progress.setValue(100)
        self._cleanup_tmp()

    def _on_preview_ended(self):
        self._countdown_timer.stop()
        self.countdown_label.setText("")
        self._update_controls("stopped")

    # ------------------------- 控制 -------------------------
    def _toggle_pause(self):
        if self.player is None or self._busy:
            return
        if self.player.paused:
            self.player.resume()
        else:
            self.player.pause()

    def _stop(self):
        if self.player is None:
            return
        self.player.stop()
        self._countdown_timer.stop()
        self.current_word.setText("已停止")
        self.countdown_label.setText("")
        self._cleanup_tmp()

    def apply_settings(self):
        if self.player is not None:
            self.player.set_gaps(
                int(self.config.word_pause * 1000),
                int(self.config.rep_gap * 1000),
            )

    def _update_controls(self, state):
        generating = state == "generating"
        playing = state == "playing"
        paused = state == "paused"

        self.start_btn.setEnabled(not generating)
        self.pause_btn.setEnabled(playing or paused)
        self.stop_btn.setEnabled(playing or paused)
        self.prev_btn.setEnabled(True)
        self.next_btn.setEnabled(True)
        self.import_btn.setEnabled(not generating)
        self.clear_btn.setEnabled(not generating)
        self.save_btn.setEnabled(not generating)
        self.text_edit.setEnabled(not generating)

        if paused:
            self.pause_btn.setText("继续")
            self.pause_btn.setIcon(FluentIcon.PLAY)
        else:
            self.pause_btn.setText("暂停")
            self.pause_btn.setIcon(FluentIcon.PAUSE)

    # ------------------------- 配置项读取 -------------------------
    def _reps(self):
        return getattr(self, "_reps_val", self.config.repetitions)

    def _rate(self):
        return getattr(self, "_rate_val", self.config.rate)

    def _pitch(self):
        return getattr(self, "_pitch_val", self.config.pitch)

    def _word_pause(self):
        return getattr(self, "_wp_val", self.config.word_pause)

    def _rep_gap(self):
        return getattr(self, "_rg_val", self.config.rep_gap)

    def _cleanup_tmp(self):
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None

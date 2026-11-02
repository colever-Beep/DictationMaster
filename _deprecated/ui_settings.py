"""设置界面：发音人、语速、音调、遍数、间隔、主题。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QMessageBox

from qfluentwidgets import (
    CardWidget, ComboBox, Slider, SpinBox, DoubleSpinBox,
    SwitchButton, PushButton, SubtitleLabel, BodyLabel, FluentIcon,
)
from core.config import Config
from core.tts import VoiceFetcher


class SettingsInterface(QWidget):
    config_applied = Signal()
    theme_toggled = Signal(bool)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.voices = []

        self._build_ui()
        self._load_from_config()
        self._fetch_voices(auto=True)

    # ------------------------- UI -------------------------
    def _card(self, title, control, sub=None):
        c = CardWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(16, 14, 16, 14)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(BodyLabel(title))
        if sub:
            s = BodyLabel(sub)
            s.setStyleSheet("color: #888888; font-size: 12px;")
            left.addWidget(s)
        h.addLayout(left)
        h.addStretch(1)
        if isinstance(control, tuple):
            for w in control:
                h.addWidget(w)
        else:
            h.addWidget(control)
        return c

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        root.addWidget(sa)

        content = QWidget()
        sa.setWidget(content)
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 22, 28, 22)
        v.setSpacing(14)

        v.addWidget(SubtitleLabel("设置"))
        v.addWidget(BodyLabel("朗读节奏与外观偏好会即时保存到本机"))

        # 发音人
        self.voice_combo = ComboBox()
        self.voice_combo.setMinimumWidth(300)
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        self.refresh_btn = PushButton(text="刷新列表", icon=FluentIcon.SYNC)
        self.refresh_btn.clicked.connect(lambda: self._fetch_voices(auto=False))
        self.voice_card = self._card("发音人", (self.voice_combo, self.refresh_btn),
                                     "选择朗读者声音（默认中文女声）")
        v.addWidget(self.voice_card)

        # 语速
        self.rate_slider = Slider(Qt.Horizontal)
        self.rate_slider.setRange(-50, 50)
        self.rate_slider.setMinimumWidth(280)
        self.rate_label = BodyLabel("0%")
        self.rate_label.setMinimumWidth(48)
        self.rate_slider.valueChanged.connect(self._on_rate_changed)
        self.rate_card = self._card("朗读速度", (self.rate_slider, self.rate_label),
                                    "负数变慢，正数变快")
        v.addWidget(self.rate_card)

        # 音调
        self.pitch_slider = Slider(Qt.Horizontal)
        self.pitch_slider.setRange(-20, 20)
        self.pitch_slider.setMinimumWidth(280)
        self.pitch_label = BodyLabel("0Hz")
        self.pitch_label.setMinimumWidth(48)
        self.pitch_slider.valueChanged.connect(self._on_pitch_changed)
        self.pitch_card = self._card("音调", (self.pitch_slider, self.pitch_label),
                                     "负数低沉，正数尖亮")
        v.addWidget(self.pitch_card)

        # 朗读遍数
        self.reps_spin = SpinBox()
        self.reps_spin.setRange(1, 5)
        self.reps_spin.valueChanged.connect(self._on_reps_changed)
        self.reps_card = self._card("朗读遍数", self.reps_spin, "每个词重复朗读的次数")
        v.addWidget(self.reps_card)

        # 词间间隔
        self.wp_spin = DoubleSpinBox()
        self.wp_spin.setRange(1.0, 15.0)
        self.wp_spin.setSingleStep(0.5)
        self.wp_spin.setSuffix(" 秒")
        self.wp_spin.valueChanged.connect(self._on_wp_changed)
        self.wp_card = self._card("词间间隔", self.wp_spin, "两个词之间的停顿")
        v.addWidget(self.wp_card)

        # 重复间隔
        self.rg_spin = DoubleSpinBox()
        self.rg_spin.setRange(0.0, 10.0)
        self.rg_spin.setSingleStep(0.5)
        self.rg_spin.setSuffix(" 秒")
        self.rg_spin.valueChanged.connect(self._on_rg_changed)
        self.rg_card = self._card("重复间隔", self.rg_spin, "同一词两遍之间的停顿")
        v.addWidget(self.rg_card)

        # 倒计时提示
        self.cd_switch = SwitchButton()
        self.cd_switch.checkedChanged.connect(self._on_cd_changed)
        self.cd_card = self._card("倒计时提示", self.cd_switch, "停顿期显示「X 秒后播放下一个」")
        v.addWidget(self.cd_card)

        # 主题
        self.theme_switch = SwitchButton()
        self.theme_switch.checkedChanged.connect(self._on_theme_changed)
        self.theme_card = self._card("深色模式", self.theme_switch, "切换浅色 / 深色界面")
        v.addWidget(self.theme_card)

        v.addStretch(1)

    # ------------------------- 读取配置 -------------------------
    def _load_from_config(self):
        self.rate_slider.setValue(self.config.rate)
        self.rate_label.setText(f"{self.config.rate:+d}%")
        self.pitch_slider.setValue(self.config.pitch)
        self.pitch_label.setText(f"{self.config.pitch:+d}Hz")
        self.reps_spin.setValue(self.config.repetitions)
        self.wp_spin.setValue(self.config.word_pause)
        self.rg_spin.setValue(self.config.rep_gap)
        self.cd_switch.setChecked(self.config.countdown_enabled)
        self.theme_switch.setChecked(self.config.theme == "dark")

    # ------------------------- 发音人 -------------------------
    def _fetch_voices(self, auto=False):
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("获取中…")
        self._fetcher = VoiceFetcher("zh")
        self._fetcher.done.connect(lambda vs: self._on_voices(vs, auto))
        self._fetcher.errored.connect(lambda e: self._on_voices_error(e, auto))
        self._fetcher.start()

    def _on_voices(self, voices, auto):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("刷新列表")
        self.voices = voices or []
        if not self.voices:
            self.voices = [(s, f, "zh-CN") for s, f in self.config.FALLBACK_VOICES]
        self._populate_voices()

    def _on_voices_error(self, err, auto):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("刷新列表")
        if not auto:
            QMessageBox.warning(self, "获取失败",
                                f"无法获取发音人列表（可能离线）：\n{err}")
        self.voices = [(s, f, "zh-CN") for s, f in self.config.FALLBACK_VOICES]
        self._populate_voices()

    def _populate_voices(self):
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for short, friendly, locale in self.voices:
            self.voice_combo.addItem(friendly, short)
        idx = self.voice_combo.findData(self.config.voice)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)
        elif self.voice_combo.count():
            self.voice_combo.setCurrentIndex(0)
            self.config.voice = self.voices[0][0]
        self.voice_combo.blockSignals(False)

    # ------------------------- 变更回调 -------------------------
    def _on_voice_changed(self, idx):
        if idx < 0:
            return
        self.config.voice = self.voice_combo.itemData(idx)
        self.config_applied.emit()

    def _on_rate_changed(self, v):
        self.config.rate = v
        self.rate_label.setText(f"{v:+d}%")

    def _on_pitch_changed(self, v):
        self.config.pitch = v
        self.pitch_label.setText(f"{v:+d}Hz")

    def _on_reps_changed(self, v):
        self.config.repetitions = v
        self.config_applied.emit()

    def _on_wp_changed(self, v):
        self.config.word_pause = v
        self.config_applied.emit()

    def _on_rg_changed(self, v):
        self.config.rep_gap = v
        self.config_applied.emit()

    def _on_cd_changed(self, checked):
        self.config.countdown_enabled = bool(checked)

    def _on_theme_changed(self, checked):
        self.config.theme = "dark" if checked else "light"
        self.theme_toggled.emit(checked)

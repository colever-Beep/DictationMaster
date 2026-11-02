"""报读参数卡片（规范 §F2 / §F2.13）。

把全部报读参数（遍数 / 间隔 / 遍间停顿 / 语速 / 音量 / 音调 / 音色模式 /
播报顺序 / 循环 / 提示音 / 纸笔模式 / 结束后显示答案）以 Fluent 控件呈现，
并支持报读方案预设的保存 / 加载 / 删除（持久化到 ``presets.json``）。

组件只读写 ``app_config.cfg``，不直接驱动播放；``build_config(subject)`` 负责
把当前配置 + 学科拼装成 ``PlayConfig`` 交给状态机。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    DoubleSpinBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    Slider,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TitleLabel,
)

from app_config import cfg
from core.dictation_engine import PlayConfig
from core.voice import default_voices
from data.repository import delete_preset, list_presets, save_preset
from ui.dialogs.base import TextInputDialog

# ---------------------------------------------------------------------- 取值辅助
# edge-tts 的 rate/volume/pitch 必须带符号（"+10%" / "-10%" / "+0Hz"）


def _to_pct(s: str) -> int:
    try:
        return int(str(s).replace("%", "").replace("+", ""))
    except (ValueError, TypeError):
        return 0


def _fmt_pct(v: int) -> str:
    return f"{v:+d}%"


def _to_hz(s: str) -> int:
    try:
        return int(str(s).replace("Hz", "").replace("+", ""))
    except (ValueError, TypeError):
        return 0


def _fmt_hz(v: int) -> str:
    return f"{v:+d}Hz"


_VOICE_MODE_ITEMS = [("女声", "female"), ("男声", "male"), ("男女混读", "mixed")]
_MODE_TO_TEXT = {m: t for t, m in _VOICE_MODE_ITEMS}
_TEXT_TO_MODE = {t: m for t, m in _VOICE_MODE_ITEMS}


class ParamCard(CardWidget):
    """报读参数卡片。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presets: dict[str, dict] = {}
        self._suppress = False  # 防止「应用预设」时回写造成递归

        self._build_ui()
        self.refresh_presets()

    # ------------------------------------------------------------------ UI 构建
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(TitleLabel("报读参数", self))

        # 每遍朗读次数
        self._repeat = SpinBox(self)
        self._repeat.setRange(1, 3)
        self._repeat.setValue(int(cfg.repeat.value))
        self._repeat.valueChanged.connect(lambda v: setattr(cfg.repeat, "value", int(v)))
        root.addLayout(self._row("每词朗读次数", self._repeat, "次"))

        # 词间书写间隔（Slider + SpinBox 联动）
        interval_row = QHBoxLayout()
        self._interval_slider = Slider(Qt.Orientation.Horizontal, self)
        self._interval_slider.setRange(3, 30)
        self._interval_slider.setValue(int(cfg.interval.value))
        self._interval_spin = SpinBox(self)
        self._interval_spin.setRange(3, 30)
        self._interval_spin.setValue(int(cfg.interval.value))
        self._interval_slider.valueChanged.connect(
            lambda v: (self._interval_spin.setValue(v),
                       setattr(cfg.interval, "value", int(v))))
        self._interval_spin.valueChanged.connect(
            lambda v: (self._interval_slider.setValue(int(v)),
                       setattr(cfg.interval, "value", int(v))))
        interval_row.addWidget(self._interval_slider, 1)
        interval_row.addWidget(self._interval_spin)
        interval_row.addWidget(BodyLabel("秒", self))
        interval_wrap = QWidget(self)
        interval_wrap.setLayout(interval_row)
        root.addLayout(self._labeled("词间书写间隔", interval_wrap))

        # 朗读遍数之间停顿
        self._inner = DoubleSpinBox(self)
        self._inner.setRange(0.5, 5.0)
        self._inner.setSingleStep(0.5)
        self._inner.setValue(float(cfg.inner_pause.value))
        self._inner.valueChanged.connect(
            lambda v: setattr(cfg.inner_pause, "value", float(v)))
        root.addLayout(self._row("遍间停顿", self._inner, "秒"))

        # 语速
        self._rate = SpinBox(self)
        self._rate.setRange(-50, 50)
        self._rate.setValue(_to_pct(cfg.rate.value))
        self._rate.valueChanged.connect(
            lambda v: setattr(cfg.rate, "value", _fmt_pct(int(v))))
        root.addLayout(self._row("语速", self._rate, "%"))

        # 音量
        self._volume = SpinBox(self)
        self._volume.setRange(0, 100)
        self._volume.setValue(_to_pct(cfg.volume.value))
        self._volume.valueChanged.connect(
            lambda v: setattr(cfg.volume, "value", _fmt_pct(int(v))))
        root.addLayout(self._row("音量", self._volume, "%"))

        # 音调
        self._pitch = SpinBox(self)
        self._pitch.setRange(-50, 50)
        self._pitch.setValue(_to_hz(cfg.pitch.value))
        self._pitch.valueChanged.connect(
            lambda v: setattr(cfg.pitch, "value", _fmt_hz(int(v))))
        root.addLayout(self._row("音调", self._pitch, "Hz"))

        # 音色模式
        self._voice_mode = ComboBox(self)
        self._voice_mode.addItems([t for t, _ in _VOICE_MODE_ITEMS])
        self._voice_mode.setCurrentText(_MODE_TO_TEXT.get(cfg.voice_mode.value, "男女混读"))
        self._voice_mode.currentTextChanged.connect(
            lambda t: setattr(cfg.voice_mode, "value", _TEXT_TO_MODE.get(t, "mixed")))
        root.addLayout(self._row("音色模式", self._voice_mode))

        # 开关组
        self._sw_shuffle = self._switch(cfg.shuffle.value,
                                       lambda v: setattr(cfg.shuffle, "value", v))
        self._sw_loop = self._switch(cfg.loop.value,
                                     lambda v: setattr(cfg.loop, "value", v))
        self._sw_cbeep = self._switch(cfg.countdown_beep.value,
                                      lambda v: setattr(cfg.countdown_beep, "value", v))
        self._sw_wbeep = self._switch(cfg.word_beep.value,
                                      lambda v: setattr(cfg.word_beep, "value", v))
        self._sw_ebeep = self._switch(cfg.end_beep.value,
                                      lambda v: setattr(cfg.end_beep, "value", v))
        self._sw_paper = self._switch(cfg.paper_mode.value,
                                      lambda v: setattr(cfg.paper_mode, "value", v))
        self._sw_answer = self._switch(
            cfg.show_answer_at_end.value,
            lambda v: setattr(cfg.show_answer_at_end, "value", v))
        root.addLayout(self._switch_row("播报顺序（随机打乱）", self._sw_shuffle))
        root.addLayout(self._switch_row("整表循环", self._sw_loop))
        root.addLayout(self._switch_row("开始前 3-2-1 提示音", self._sw_cbeep))
        root.addLayout(self._switch_row("每词开始短提示音", self._sw_wbeep))
        root.addLayout(self._switch_row("结束提示音", self._sw_ebeep))
        root.addLayout(self._switch_row("纸笔模式（隐藏词语）", self._sw_paper))
        root.addLayout(self._switch_row("结束后显示答案", self._sw_answer))

        root.addWidget(StrongBodyLabel("报读方案预设", self))
        preset_row = QHBoxLayout()
        self._preset_combo = ComboBox(self)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self._preset_combo, 1)
        save_btn = PrimaryPushButton("保存预设", self)
        save_btn.setIcon(FluentIcon.SAVE)
        save_btn.clicked.connect(self._on_save_preset)
        del_btn = PushButton("删除预设", self)
        del_btn.setIcon(FluentIcon.DELETE)
        del_btn.clicked.connect(self._on_delete_preset)
        preset_row.addWidget(save_btn)
        preset_row.addWidget(del_btn)
        root.addLayout(preset_row)

        root.addStretch(1)

    # ------------------------------------------------------------------ 行构造辅助
    @staticmethod
    def _row(label: str, control: QWidget, suffix: str = "") -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(BodyLabel(label, control.parentWidget() or control))
        h.addStretch(1)
        h.addWidget(control)
        if suffix:
            h.addWidget(BodyLabel(suffix, control.parentWidget() or control))
        return h

    @staticmethod
    def _labeled(label: str, control: QWidget) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(BodyLabel(label, control.parentWidget() or control))
        h.addStretch(1)
        h.addWidget(control)
        return h

    @staticmethod
    def _switch(value: bool, slot) -> SwitchButton:
        sw = SwitchButton()
        sw.setChecked(bool(value))
        sw.checkedChanged.connect(slot)
        return sw

    @staticmethod
    def _switch_row(label: str, sw: SwitchButton) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(BodyLabel(label, sw.parentWidget() or sw))
        h.addStretch(1)
        h.addWidget(sw)
        return h

    # ------------------------------------------------------------------ 预设
    def refresh_presets(self) -> None:
        """刷新预设下拉列表。"""
        self._presets = {p["name"]: p for p in list_presets()}
        self._suppress = True
        self._preset_combo.clear()
        self._preset_combo.addItem("（不使用预设）")
        for name in sorted(self._presets.keys()):
            self._preset_combo.addItem(name)
        self._suppress = False

    def _on_preset_selected(self, name: str) -> None:
        if self._suppress:
            return
        if name in self._presets:
            self.apply_preset(self._presets[name])

    def apply_preset(self, p: dict) -> None:
        """把一个预设 dict 写回 cfg 并刷新控件。"""
        self._suppress = True
        try:
            cfg.repeat.value = int(p.get("repeat", cfg.repeat.value))
            cfg.interval.value = float(p.get("interval", cfg.interval.value))
            cfg.inner_pause.value = float(p.get("inner_pause", cfg.inner_pause.value))
            cfg.rate.value = str(p.get("rate", cfg.rate.value))
            cfg.volume.value = str(p.get("volume", cfg.volume.value))
            cfg.pitch.value = str(p.get("pitch", cfg.pitch.value))
            cfg.voice_mode.value = str(p.get("voice_mode", cfg.voice_mode.value))
            cfg.shuffle.value = bool(p.get("shuffle", cfg.shuffle.value))
            cfg.loop.value = bool(p.get("loop", cfg.loop.value))
            cfg.countdown_beep.value = bool(p.get("countdown_beep", cfg.countdown_beep.value))
            cfg.word_beep.value = bool(p.get("word_beep", cfg.word_beep.value))
            cfg.end_beep.value = bool(p.get("end_beep", cfg.end_beep.value))
            cfg.paper_mode.value = bool(p.get("paper_mode", cfg.paper_mode.value))
            cfg.show_answer_at_end.value = bool(
                p.get("show_answer_at_end", cfg.show_answer_at_end.value))
            self._sync_widgets()
        finally:
            self._suppress = False

    def _sync_widgets(self) -> None:
        """把 cfg 当前值同步到所有控件显示。"""
        self._repeat.setValue(int(cfg.repeat.value))
        self._interval_slider.setValue(int(cfg.interval.value))
        self._interval_spin.setValue(int(cfg.interval.value))
        self._inner.setValue(float(cfg.inner_pause.value))
        self._rate.setValue(_to_pct(cfg.rate.value))
        self._volume.setValue(_to_pct(cfg.volume.value))
        self._pitch.setValue(_to_hz(cfg.pitch.value))
        self._voice_mode.setCurrentText(_MODE_TO_TEXT.get(cfg.voice_mode.value, "男女混读"))
        self._sw_shuffle.setChecked(bool(cfg.shuffle.value))
        self._sw_loop.setChecked(bool(cfg.loop.value))
        self._sw_cbeep.setChecked(bool(cfg.countdown_beep.value))
        self._sw_wbeep.setChecked(bool(cfg.word_beep.value))
        self._sw_ebeep.setChecked(bool(cfg.end_beep.value))
        self._sw_paper.setChecked(bool(cfg.paper_mode.value))
        self._sw_answer.setChecked(bool(cfg.show_answer_at_end.value))

    def _on_save_preset(self) -> None:
        dlg = TextInputDialog("保存报读方案", "方案名称", "", self)
        if dlg.exec():
            name = dlg.text_value()
            if not name:
                return
            preset = {
                "name": name,
                "repeat": int(cfg.repeat.value),
                "interval": float(cfg.interval.value),
                "inner_pause": float(cfg.inner_pause.value),
                "rate": str(cfg.rate.value),
                "volume": str(cfg.volume.value),
                "pitch": str(cfg.pitch.value),
                "voice_mode": str(cfg.voice_mode.value),
                "shuffle": bool(cfg.shuffle.value),
                "loop": bool(cfg.loop.value),
                "countdown_beep": bool(cfg.countdown_beep.value),
                "word_beep": bool(cfg.word_beep.value),
                "end_beep": bool(cfg.end_beep.value),
                "paper_mode": bool(cfg.paper_mode.value),
                "show_answer_at_end": bool(cfg.show_answer_at_end.value),
            }
            save_preset(preset)
            self.refresh_presets()
            idx = self._preset_combo.findText(name)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
            InfoBar.success("已保存", f"报读方案「{name}」已保存。",
                            position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _on_delete_preset(self) -> None:
        name = self._preset_combo.currentText()
        if name in self._presets:
            delete_preset(name)
            self.refresh_presets()
            InfoBar.info("已删除", f"报读方案「{name}」已删除。",
                         position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    # ------------------------------------------------------------------ 拼装
    def build_config(self, subject: str) -> PlayConfig:
        """根据当前 cfg + 学科拼装 ``PlayConfig``（含已解析音色列表）。"""
        mode = cfg.voice_mode.value
        voices = default_voices(subject, mode)
        return PlayConfig(
            subject=subject,
            rate=str(cfg.rate.value),
            volume=str(cfg.volume.value),
            pitch=str(cfg.pitch.value),
            repeat=int(cfg.repeat.value),
            interval=float(cfg.interval.value),
            inner_pause=float(cfg.inner_pause.value),
            shuffle=bool(cfg.shuffle.value),
            loop=bool(cfg.loop.value),
            countdown_beep=bool(cfg.countdown_beep.value),
            word_beep=bool(cfg.word_beep.value),
            end_beep=bool(cfg.end_beep.value),
            paper_mode=bool(cfg.paper_mode.value),
            show_answer_at_end=bool(cfg.show_answer_at_end.value),
            voices=voices,
            announce=bool(cfg.announce_enabled.value),
            concurrency=int(cfg.concurrency.value),
        )

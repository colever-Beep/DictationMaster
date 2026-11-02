"""全局配置持久化（基于 QSettings，自动适配各用户，不硬编码路径）。"""
from PySide6.QtCore import QSettings, QStandardPaths, QDir


class Config:
    # 默认中文发音人（当无法联网获取时使用）
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

    # 内置常见中文发音人（离线兜底列表）
    FALLBACK_VOICES = [
        ("zh-CN-XiaoxiaoNeural", "晓晓（女声·温柔）"),
        ("zh-CN-YunxiNeural", "云希（男声·活泼）"),
        ("zh-CN-YunyangNeural", "云扬（男声·专业）"),
        ("zh-CN-XiaoyiNeural", "晓伊（女声）"),
        ("zh-CN-YunjianNeural", "云健（男声）"),
        ("zh-CN-XiaochenNeural", "晓辰（女声）"),
        ("zh-CN-XiaohanNeural", "晓涵（女声）"),
        ("zh-CN-XiaomengNeural", "晓梦（女声·萌）"),
        ("zh-CN-XiaoruiNeural", "晓睿（女声·成熟）"),
        ("zh-CN-YunfengNeural", "云枫（男声）"),
        ("zh-CN-YunhaoNeural", "云皓（男声·童声）"),
        ("zh-CN-YunxiaNeural", "云夏（女声）"),
        ("zh-CN-YunyeNeural", "云叶（女声）"),
        ("zh-CN-YunzeNeural", "云泽（男声·抒情）"),
        ("zh-CN-liaoning-XiaobeiNeural", "晓北（辽宁·女声）"),
        ("zh-CN-shaanxi-XiaoniNeural", "晓妮（陕西·女声）"),
        ("zh-TW-HsiaoChenNeural", "晓臻（台湾·女声）"),
        ("zh-TW-HsiaoYuNeural", "晓雨（台湾·女声）"),
        ("zh-TW-YunJheNeural", "云哲（台湾·男声）"),
    ]

    def __init__(self):
        self._s = QSettings("TingxieApp", "EdgeTTS_Dictation")

    # ---- 基础路径 ----
    def download_dir(self) -> str:
        d = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not d:
            d = QDir.homePath()
        return d

    # ---- 通用读写 ----
    def _get(self, key, default):
        v = self._s.value(key)
        return v if v is not None else default

    def _set(self, key, value):
        self._s.setValue(key, value)
        self._s.sync()

    # ---- 具体配置项 ----
    @property
    def voice(self):
        return self._get("voice", self.DEFAULT_VOICE)

    @voice.setter
    def voice(self, v):
        self._set("voice", v)

    @property
    def rate(self):  # 整型，单位 %
        return int(self._get("rate", 0))

    @rate.setter
    def rate(self, v):
        self._set("rate", int(v))

    @property
    def pitch(self):  # 整型，单位 Hz
        return int(self._get("pitch", 0))

    @pitch.setter
    def pitch(self, v):
        self._set("pitch", int(v))

    @property
    def repetitions(self):  # 朗读遍数
        return int(self._get("repetitions", 1))

    @repetitions.setter
    def repetitions(self, v):
        self._set("repetitions", int(v))

    @property
    def word_pause(self):  # 词间间隔（秒）
        return float(self._get("word_pause", 3.0))

    @word_pause.setter
    def word_pause(self, v):
        self._set("word_pause", float(v))

    @property
    def rep_gap(self):  # 重复间隔（秒）
        return float(self._get("rep_gap", 1.0))

    @rep_gap.setter
    def rep_gap(self, v):
        self._set("rep_gap", float(v))

    @property
    def theme(self):  # "light" / "dark"
        return self._get("theme", "light")

    @theme.setter
    def theme(self, v):
        self._set("theme", v)

    @property
    def words(self):  # 上次词库文本
        return self._get("words", "")

    @words.setter
    def words(self, v):
        self._set("words", v)

    @property
    def countdown_enabled(self):
        return bool(self._get("countdown_enabled", True))

    @countdown_enabled.setter
    def countdown_enabled(self, v):
        self._set("countdown_enabled", bool(v))

    def rate_str(self) -> str:
        return f"{self.rate:+d}%"

    def pitch_str(self) -> str:
        return f"{self.pitch:+d}Hz"

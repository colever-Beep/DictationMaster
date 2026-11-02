"""全局配置：基于 qfluentwidgets 的 QConfig 持久化所有用户设置。

配置落盘路径由 core.paths 提供（%LOCALAPPDATA%/DictationMaster/config.json）。
本模块只声明配置项与默认值，不创建任何 UI；UI 通过 cfg.<item> 读写，
并连接 valueChanged 信号实现主题等即时生效与持久化。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from qfluentwidgets import (
    QConfig,
    ConfigItem,
    OptionsConfigItem,
    OptionsValidator,
    RangeConfigItem,
    RangeValidator,
    BoolValidator,
    EnumSerializer,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
)

from core.paths import CONFIG_FILE, CACHE_DIR

# 强调色（Fluent 蓝），贯穿整个应用
ACCENT_COLOR = QColor("#0F6CBD")


class Config(QConfig):
    """听写助手的全局配置项集合。"""

    # 通用
    theme = OptionsConfigItem(
        "general", "theme", Theme.LIGHT,
        validator=OptionsValidator([Theme.LIGHT, Theme.DARK, Theme.AUTO]),
        serializer=EnumSerializer(Theme),
    )
    subject = OptionsConfigItem(
        "general", "subject", "chinese",
        validator=OptionsValidator(["chinese", "english"]),
    )
    check_network_on_start = ConfigItem("general", "check_network_on_start", True,
                                        validator=BoolValidator())
    first_run_done = ConfigItem("general", "first_run_done", False,
                                validator=BoolValidator())

    # 语音
    default_voice_zh = ConfigItem("voice", "default_voice_zh", "zh-CN-XiaoxiaoNeural")
    default_voice_en = ConfigItem("voice", "default_voice_en", "en-US-AriaNeural")
    voice_mode = OptionsConfigItem(
        "voice", "voice_mode", "mixed",
        validator=OptionsValidator(["female", "male", "mixed"]),
    )
    # 合成并发数（规范 §F5：1–8）
    concurrency = RangeConfigItem("voice", "concurrency", 4,
                                  validator=RangeValidator(1, 8))
    proxy = ConfigItem("voice", "proxy", "")
    # 离线引擎：开启后改用本地 Kokoro（无需联网，断网可用）；关闭则用在线 Edge
    kokoro_enabled = ConfigItem("voice", "kokoro_enabled", False,
                                validator=BoolValidator())
    # 听写信息播报：开始前播报词数/遍数/书写时间并提示确认音量；结束后播报「听写结束」
    announce_enabled = ConfigItem("voice", "announce_enabled", True,
                                  validator=BoolValidator())

    # 报读参数
    rate = ConfigItem("params", "rate", "-10%")
    volume = ConfigItem("params", "volume", "+0%")
    pitch = ConfigItem("params", "pitch", "+0Hz")
    repeat = ConfigItem("params", "repeat", 2)
    interval = ConfigItem("params", "interval", 10)
    inner_pause = ConfigItem("params", "inner_pause", 1.5)
    shuffle = ConfigItem("params", "shuffle", False)
    loop = ConfigItem("params", "loop", False)
    paper_mode = ConfigItem("params", "paper_mode", True)
    show_answer_at_end = ConfigItem("params", "show_answer_at_end", True)
    countdown_beep = ConfigItem("params", "countdown_beep", True)
    word_beep = ConfigItem("params", "word_beep", False)
    end_beep = ConfigItem("params", "end_beep", True)

    # GitHub 同步（教师上传任务 / 教室端拉取，跨电脑无服务器方案）
    github_enabled = ConfigItem("github", "github_enabled", False,
                               validator=BoolValidator())
    github_owner = ConfigItem("github", "github_owner", "")
    github_repo = ConfigItem("github", "github_repo", "")
    github_branch = ConfigItem("github", "github_branch", "main")
    github_token = ConfigItem("github", "github_token", "")
    github_tasks_path = ConfigItem("github", "github_tasks_path", "tasks")
    # 上传默认设置：布置任务时的默认行为（可在「设置 → GitHub 同步」调整）
    github_auto_upload = ConfigItem("github", "github_auto_upload", False,
                                    validator=BoolValidator())
    github_upload_overwrite = ConfigItem("github", "github_upload_overwrite", True,
                                         validator=BoolValidator())

    # 存储
    cache_dir = ConfigItem("storage", "cache_dir", str(CACHE_DIR))


# 全局唯一配置实例（被 qconfig 注册，qconfig.load/save 会读写其值）
cfg = Config()


def init_config() -> None:
    """初始化配置文件路径并加载已保存的值（需在创建配置实例后调用）。

    注意：必须把自定义 ``cfg`` 实例作为 ``config=`` 参数传给 ``qconfig.load``，
    否则 qfluentwidgets 只会读写其内置单例、而不会持久化 ``cfg`` 上的配置项
    （典型症状：首次启动引导每次启动都弹出，主题/学科/代理等设置不生效）。
    """
    qconfig.load(file=CONFIG_FILE, config=cfg)
    # 缓存目录若被用户改到别处，确保存在
    Path(str(cfg.cache_dir.value)).mkdir(parents=True, exist_ok=True)


def apply_theme() -> None:
    """应用当前主题与强调色（必须在 QApplication 创建之后调用）。"""
    setTheme(cfg.theme.value)
    setThemeColor(ACCENT_COLOR)

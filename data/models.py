"""数据模型：词条、词表、报读预设、会话记录。

对应规范 §6 的数据结构。此处仅定义纯数据结构（dataclass），
不涉及 JSON / SQLite 读写（见 M3 的 repository）。字段与 §6.1 / §6.2 对齐，
便于后续直接序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Subject(str, Enum):
    """学科。"""

    CHINESE = "chinese"
    ENGLISH = "english"


class WordStatus(str, Enum):
    """听写结果状态。"""

    MASTERED = "mastered"  # 已掌握
    WRONG = "wrong"        # 写错
    UNKNOWN = "unknown"    # 未标记


@dataclass
class SpeakParams:
    """一次报读的语音参数（对应 §6.2 预设中的语音字段）。"""

    rate: str = "-10%"
    volume: str = "+0%"
    pitch: str = "+0Hz"


@dataclass
class WordItem:
    """单个词条。alias 用于多音字 / 英文缩写 / 数字读法的特殊读法。"""

    id: str
    text: str
    alias: str = ""
    lang: str = "zh"
    enabled: bool = True
    repeat: Optional[int] = None       # None 表示继承全局报读参数
    interval: Optional[float] = None   # 同上
    note: str = ""


@dataclass
class WordList:
    """词表。

    - ``builtin``：True 表示内置/默认词表（来自教材，如人教版单元），False 为用户自建。
    - ``grade``：年级分类，仅对内置词表有意义（"" / "小学" / "初中" / "高中"），
      用于「词表」页按 小学/初中/高中 归类展示。
    """

    id: str
    name: str
    subject: str = "chinese"
    items: list[WordItem] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    builtin: bool = False
    grade: str = ""


@dataclass
class Preset:
    """报读方案预设（对应 §6.2 presets.json）。"""

    name: str
    repeat: int = 2
    interval: float = 10.0
    inner_pause: float = 1.5
    rate: str = "-10%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    voice_mode: str = "mixed"
    voices: list[str] = field(default_factory=list)
    shuffle: bool = False
    loop: bool = False
    countdown_beep: bool = True
    word_beep: bool = False
    end_beep: bool = True
    paper_mode: bool = True
    show_answer_at_end: bool = True


@dataclass
class DictationAssignment:
    """教师布置的听写任务（备课时一次性设定范围与参数，课代表次日一键执行）。

    - ``wordlist_id``：来源词表（落库时快照 name/subject 以便词表被删后仍可读）。
    - ``selected_ids``：本次要听写的词条 id 列表；为空表示听写整表。
    - ``config``：听写时的完整 ``PlayConfig`` 字段（dict 形式），课代表执行时直接还原。
    - ``due_date``：应完成日期（``YYYY-MM-DD``），默认布置日的次日。
    - ``done``：课代表执行完成后置 True，不再出现在待办中（可在管理页重置）。
    """

    id: str
    name: str
    wordlist_id: str
    wordlist_name: str
    subject: str
    selected_ids: list[str] = field(default_factory=list)
    words: list[dict] = field(default_factory=list)  # 自包含：本次范围的单词数据（跨机导入后不依赖原词表）
    config: dict = field(default_factory=dict)
    due_date: str = ""
    created_at: str = ""
    note: str = ""
    done: bool = False

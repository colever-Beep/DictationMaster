"""数据仓储：词表 / 预设 的 JSON 读写、教材词库加载、时长估算与导出。

对应规范 §6（数据模型与存储）。本模块属于 ``data`` 层，只依赖 ``core.paths`` 与
``data.models``，**不 import 任何 ui 模块**；UI 通过本模块完成持久化，便于单元测试。

存储约定：
- 词表：``%LOCALAPPDATA%/DictationMaster/wordlists/{id}.json``
- 预设：``%LOCALAPPDATA%/DictationMaster/data/presets.json``
- 教材：``%LOCALAPPDATA%/DictationMaster/textbooks/*.json``（可插拔目录）
"""

from __future__ import annotations

import csv
import glob
import io
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.paths import APP_DATA, DATA_DIR, TEXTBOOKS_DIR, WORDLISTS_DIR
from data.models import WordItem, WordList

# 随机后缀位数，降低同秒创建 id 碰撞概率
_RND = 4


def _now() -> str:
    """当前时间的可排序 ISO 字符串（到秒）。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def gen_id(prefix: str) -> str:
    """生成带时间戳与随机后缀的唯一 id。"""
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{random.randrange(10 ** _RND):0{_RND}d}"


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def wordlist_to_dict(wl: WordList) -> dict:
    """把 WordList 转为可落盘的 dict（字段顺序与 §6.1 对齐）。"""
    return {
        "schema": 1,
        "id": wl.id,
        "name": wl.name,
        "subject": wl.subject,
        "builtin": wl.builtin,
        "grade": wl.grade,
        "created_at": wl.created_at,
        "updated_at": wl.updated_at,
        "items": [
            {
                "id": it.id,
                "text": it.text,
                "alias": it.alias,
                "lang": it.lang,
                "enabled": it.enabled,
                "repeat": it.repeat,
                "interval": it.interval,
                "note": it.note,
            }
            for it in wl.items
        ],
    }


def wordlist_from_dict(d: dict) -> WordList:
    """把 dict 还原为 WordList（容忍缺字段，给默认值）。"""
    items = [
        WordItem(
            id=it.get("id") or gen_id("it"),
            text=it.get("text", ""),
            alias=it.get("alias", ""),
            lang=it.get("lang", "zh"),
            enabled=it.get("enabled", True),
            repeat=it.get("repeat"),
            interval=it.get("interval"),
            note=it.get("note", ""),
        )
        for it in d.get("items", [])
    ]
    return WordList(
        id=d.get("id") or gen_id("wl"),
        name=d.get("name", "未命名词表"),
        subject=d.get("subject", "chinese"),
        items=items,
        created_at=d.get("created_at", _now()),
        updated_at=d.get("updated_at", _now()),
        builtin=bool(d.get("builtin", False)),
        grade=d.get("grade", ""),
    )


# ---------------------------------------------------------------------------
# 词表 CRUD
# ---------------------------------------------------------------------------

def list_wordlists() -> list[WordList]:
    """返回全部词表，按更新时间倒序。"""
    result: list[WordList] = []
    for path in sorted(glob.glob(str(WORDLISTS_DIR / "*.json"))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            result.append(wordlist_from_dict(data))
        except (json.JSONDecodeError, OSError):
            # 损坏的文件跳过，不影响其余词表
            continue
    result.sort(key=lambda w: w.updated_at, reverse=True)
    return result


def get_wordlist(list_id: str) -> Optional[WordList]:
    """按 id 读取单个词表，不存在返回 None。"""
    path = WORDLISTS_DIR / f"{list_id}.json"
    if not path.exists():
        return None
    try:
        return wordlist_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def save_wordlist(wl: WordList) -> None:
    """写入词表（自动刷新 updated_at）。"""
    wl.updated_at = _now()
    path = WORDLISTS_DIR / f"{wl.id}.json"
    path.write_text(json.dumps(wordlist_to_dict(wl), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def delete_wordlist(list_id: str) -> None:
    """删除词表文件（不存在则忽略）。"""
    path = WORDLISTS_DIR / f"{list_id}.json"
    if path.exists():
        path.unlink()


def rename_wordlist(list_id: str, new_name: str) -> Optional[WordList]:
    """重命名词表并返回更新后的对象。"""
    wl = get_wordlist(list_id)
    if wl is None:
        return None
    wl.name = new_name
    save_wordlist(wl)
    return wl


def copy_wordlist(list_id: str) -> Optional[WordList]:
    """复制词表（新 id 与名称，更新时间刷新）。"""
    wl = get_wordlist(list_id)
    if wl is None:
        return None
    new = WordList(
        id=gen_id("wl"),
        name=f"{wl.name}_副本",
        subject=wl.subject,
        items=[WordItem(
            id=gen_id("it"),
            text=it.text,
            alias=it.alias,
            lang=it.lang,
            enabled=it.enabled,
            repeat=it.repeat,
            interval=it.interval,
            note=it.note,
        ) for it in wl.items],
        created_at=_now(),
        updated_at=_now(),
        # 副本归用户所有（非内置），grade 一并带上以保持年级归类信息
        builtin=False,
        grade=wl.grade,
    )
    save_wordlist(new)
    return new


def export_wordlist(wl: WordList, path: str) -> str:
    """导出词表到文件。

    按扩展名决定格式：``.csv`` 导出 UTF-8 BOM（Excel 直接可读），其余按 ``.txt``
    处理为一行一词。返回实际格式名（``"txt"`` / ``"csv"``）。
    """
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["text", "alias", "lang", "enabled"])
            for it in wl.items:
                writer.writerow([it.text, it.alias, it.lang, it.enabled])
        return "csv"
    with p.open("w", encoding="utf-8-sig") as f:
        for it in wl.items:
            f.write(it.text + "\n")
    return "txt"


# ---------------------------------------------------------------------------
# 报读方案预设（F2.13，M4 复用）
# ---------------------------------------------------------------------------

PRESETS_FILE = DATA_DIR / "presets.json"


def list_presets() -> list[dict]:
    """返回全部预设（dict 列表，按名称排序）。"""
    if not PRESETS_FILE.exists():
        return []
    try:
        data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return sorted(data, key=lambda d: d.get("name", ""))


def save_preset(preset: dict) -> None:
    """保存 / 更新一个预设（按 name 去重）。"""
    presets = list_presets()
    presets = [p for p in presets if p.get("name") != preset.get("name")]
    presets.append(preset)
    PRESETS_FILE.write_text(json.dumps(presets, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def delete_preset(name: str) -> None:
    """按名称删除预设。"""
    presets = [p for p in list_presets() if p.get("name") != name]
    PRESETS_FILE.write_text(json.dumps(presets, ensure_ascii=False, indent=2),
                            encoding="utf-8")


# ---------------------------------------------------------------------------
# 教材词库（F1.7）
# ---------------------------------------------------------------------------

@dataclass
class TextbookMeta:
    """教材词库元信息：定位一个单元文件。"""

    subject: str
    stage: str
    grade: str
    volume: str
    file: str


def list_textbooks() -> list[TextbookMeta]:
    """扫描教材目录，返回所有可用教材的元信息。"""
    metas: list[TextbookMeta] = []
    for path in sorted(glob.glob(str(TEXTBOOKS_DIR / "*.json"))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        metas.append(TextbookMeta(
            subject=data.get("subject", "chinese"),
            stage=data.get("stage", ""),
            grade=data.get("grade", ""),
            volume=data.get("volume", ""),
            file=path,
        ))
    return metas


def get_textbook_units(meta: TextbookMeta) -> list[str]:
    """返回该教材的单元名列表。"""
    try:
        data = json.loads(Path(meta.file).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [u.get("name", "") for u in data.get("units", [])]


def load_textbook_words(meta: TextbookMeta, unit_name: str) -> list[str]:
    """返回某单元的词条列表（去空、去重序保留首次出现）。"""
    try:
        data = json.loads(Path(meta.file).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for u in data.get("units", []):
        if u.get("name") == unit_name:
            return [w.strip() for w in u.get("words", []) if w.strip()]
    return []


def _bundled_root() -> Path:
    """随包资源根目录。

    - PyInstaller 打包后（``sys.frozen``）：资源在 ``sys._MEIPASS``（onedir 下即
      ``_internal`` 目录），数据文件都在这里；
    - 源码运行：项目根目录（本文件位于 ``<root>/data/repository.py``）。

    统一走这个函数，避免依赖 ``__file__`` 在冻结环境下的不确定语义。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def seed_textbooks() -> int:
    """首次运行时把内置示例教材复制到用户教材目录（可插拔目录不破坏用户自建词库）。

    返回实际复制的条数；内置目录不存在或无需复制时返回 0。
    """
    bundled = _bundled_root() / "data" / "textbooks"
    if not bundled.is_dir():
        return 0
    TEXTBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(bundled.glob("*.json")):
        dst = TEXTBOOKS_DIR / src.name
        if not dst.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            copied += 1
    return copied


# 词表首次种入标记：只种一次，之后用户删除内置词表也不会被「复活」
_WORDLIST_SEED_MARKER = ".seed_wordlists_v1"


def seed_wordlists() -> int:
    """首次运行时把随包内置词表复制到用户词表目录。

    与教材不同，词表是可直接听写的内容，用户可能主动删除；因此用版本标记保证
    **只种一次**（删除后重启不再回来）。已存在的同名文件不覆盖，保护用户修改。
    返回实际复制的条数。
    """
    marker = APP_DATA / _WORDLIST_SEED_MARKER
    if marker.exists():
        return 0
    bundled = _bundled_root() / "data" / "bundled_wordlists"
    if not bundled.is_dir():
        return 0
    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(bundled.glob("*.json")):
        dst = WORDLISTS_DIR / src.name
        if not dst.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            copied += 1
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass
    return copied


# ---------------------------------------------------------------------------
# 预计时长估算（F1.8，公式见 §5.4）
# ---------------------------------------------------------------------------

def estimate_seconds(wl: WordList, repeat: int, interval: float,
                     inner_pause: float) -> float:
    """估算整表听写耗时（秒）。

    单条音频时长 ≈ 0.35s/汉字(zh) 或 0.32s/英文词(en)，叠加语速系数（此处用线性近似）；
    每个词耗时 = inner_pause*(repeat-1) + interval + 音频时长。
    仅统计启用词条。
    """
    rate_factor = 1.0  # 语速系数：本估算用线性近似，真实时长由音频文件决定
    total = 0.0
    for it in wl.items:
        if not it.enabled:
            continue
        if it.lang == "zh":
            units = len(it.text)
            audio = units * 0.35
        else:
            units = len(it.text.split())
            audio = units * 0.32
        audio *= rate_factor
        per = inner_pause * (repeat - 1) + interval + audio
        total += per
    return total


def format_duration(seconds: float) -> str:
    """把秒数格式化为「约 X 分钟 / X 秒」中文文案。"""
    if seconds < 60:
        return f"约 {seconds:.0f} 秒"
    return f"约 {seconds / 60:.1f} 分钟"

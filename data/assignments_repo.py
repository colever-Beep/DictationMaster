"""听写布置任务的持久化（对应教师「备课布置」需求）。

存储约定：``%LOCALAPPDATA%/DictationMaster/assignments/{id}.json``

每个布置即一份「听写任务」：来源词表 + 选中的单词 id + 完整报读参数 + 截止日期。
教师备课时保存，课代表次日在同一台一体机（同一账号 / 同一数据目录）打开即可一键执行，
无需重新选词。

本模块属于 ``data`` 层，只依赖 ``core.paths`` 与 ``data.models``，**不 import 任何 ui 模块**。
"""

from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.paths import ASSIGNMENTS_DIR
from data.models import DictationAssignment, WordItem, WordList
from data.repository import gen_id, get_wordlist


def _now() -> str:
    """当前时间的可排序 ISO 字符串（到秒）。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _today() -> str:
    """今天日期字符串 ``YYYY-MM-DD``。"""
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    """明天日期字符串 ``YYYY-MM-DD``。"""
    return (datetime.now().date().toordinal() + 1) and datetime.fromordinal(
        datetime.now().date().toordinal() + 1
    ).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def assignment_to_dict(a: DictationAssignment) -> dict:
    """把 DictationAssignment 转为可落盘的 dict。"""
    return {
        "schema": 1,
        "id": a.id,
        "name": a.name,
        "wordlist_id": a.wordlist_id,
        "wordlist_name": a.wordlist_name,
        "subject": a.subject,
        "selected_ids": list(a.selected_ids),
        "words": [dict(w) for w in a.words],  # 自包含单词数据，跨机导入后不依赖原词表
        "config": dict(a.config),
        "due_date": a.due_date,
        "created_at": a.created_at,
        "note": a.note,
        "done": bool(a.done),
    }


def assignment_from_dict(d: dict) -> DictationAssignment:
    """把 dict 还原为 DictationAssignment（容忍缺字段）。"""
    return DictationAssignment(
        id=d.get("id") or gen_id("asg"),
        name=d.get("name", "未命名布置"),
        wordlist_id=d.get("wordlist_id", ""),
        wordlist_name=d.get("wordlist_name", ""),
        subject=d.get("subject", "chinese"),
        selected_ids=list(d.get("selected_ids", [])),
        words=[dict(w) for w in d.get("words", [])],
        config=dict(d.get("config", {})),
        due_date=d.get("due_date", ""),
        created_at=d.get("created_at", _now()),
        note=d.get("note", ""),
        done=bool(d.get("done", False)),
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_assignment(a: DictationAssignment) -> None:
    """写入 / 更新一份布置（id 作为文件名，便于单文件读写）。"""
    if not a.created_at:
        a.created_at = _now()
    path = ASSIGNMENTS_DIR / f"{a.id}.json"
    path.write_text(json.dumps(assignment_to_dict(a), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def get_assignment(aid: str) -> Optional[DictationAssignment]:
    """按 id 读取单个布置，不存在返回 None。"""
    path = ASSIGNMENTS_DIR / f"{aid}.json"
    if not path.exists():
        return None
    try:
        return assignment_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def list_assignments() -> list[DictationAssignment]:
    """返回全部布置，按截止日期升序（无日期排最后）、再按创建时间倒序。"""
    result: list[DictationAssignment] = []
    for path in sorted(glob.glob(str(ASSIGNMENTS_DIR / "*.json"))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            result.append(assignment_from_dict(data))
        except (json.JSONDecodeError, OSError):
            continue
    result.sort(key=lambda a: (a.due_date or "9999-99-99", a.created_at), reverse=False)
    return result


def delete_assignment(aid: str) -> None:
    """删除一份布置（不存在则忽略）。"""
    path = ASSIGNMENTS_DIR / f"{aid}.json"
    if path.exists():
        path.unlink()


def mark_done(aid: str) -> None:
    """把布置标记为已完成（课代表执行后调用）。"""
    a = get_assignment(aid)
    if a is None:
        return
    a.done = True
    save_assignment(a)


def reset_done(aid: str) -> None:
    """重置为未完成（管理页「再听一次 / 重新出现」用）。"""
    a = get_assignment(aid)
    if a is None:
        return
    a.done = False
    save_assignment(a)


# ---------------------------------------------------------------------------
# 跨机导出 / 导入（自包含布置文件，无需服务器）
# ---------------------------------------------------------------------------

def export_assignment_file(a: DictationAssignment, path: str) -> None:
    """把一份布置导出为自包含文件（含单词数据），供其它电脑导入。"""
    Path(path).write_text(
        json.dumps(assignment_to_dict(a), ensure_ascii=False, indent=2),
        encoding="utf-8")


def import_assignment_file(path: str) -> DictationAssignment:
    """从自包含布置文件导入：重新生成 id 存入本地，返回新对象。

    导入后该布置即出现在「待听写任务」中，且因自带单词数据，
    无需教室电脑上存在原词表即可直接听写。
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"布置文件无法读取：{e}") from e
    return import_assignment_dict(data)


def import_assignment_dict(data: dict) -> DictationAssignment:
    """从 dict 导入一份布置（本地文件导入用）：重新生成 id，避免与本地冲突。"""
    if not data.get("words") and not data.get("wordlist_id"):
        raise ValueError("该数据不是有效的布置（缺少单词或词表信息）。")
    a = assignment_from_dict(data)
    a.id = gen_id("asg")          # 避免与本地已有布置 id 冲突
    a.done = False                # 导入即视为待听写
    a.created_at = _now()
    save_assignment(a)
    return a


def upsert_assignment_dict(data: dict) -> DictationAssignment:
    """从 dict 导入一份布置（GitHub 拉取用）：保留远程原始 id 直接落盘。

    保留 id 是为了「按 id 去重」——重复拉取同一份远程任务不会生成多份副本。
    """
    if not data.get("words") and not data.get("wordlist_id"):
        raise ValueError("该数据不是有效的布置（缺少单词或词表信息）。")
    a = assignment_from_dict(data)
    save_assignment(a)            # 沿用 a.id（远程原始 id）
    return a


def build_wordlist_from_assignment(a: DictationAssignment) -> WordList:
    """把一份布置还原成可直接听写的 ``WordList``。

    优先使用布置中自包含的单词数据（跨机导入场景，教室电脑可能无原词表）；
    仅当无 ``words`` 数据时回退到本地词表查找并按 ``selected_ids`` 过滤。
    """
    if a.words:
        items = [WordItem(
            id=w.get("id") or gen_id("it"),
            text=w.get("text", ""),
            alias=w.get("alias", ""),
            lang=w.get("lang", "zh"),
            note=w.get("note", ""),
        ) for w in a.words]
    else:
        wl = get_wordlist(a.wordlist_id)
        if wl is None:
            raise FileNotFoundError(f"来源词表「{a.wordlist_name}」不存在")
        if a.selected_ids:
            idset = set(a.selected_ids)
            items = [it for it in wl.items if it.id in idset]
        else:
            items = list(wl.items)
    subject = a.subject or (items[0].lang == "en" and "english" or "chinese")
    return WordList(
        id=a.wordlist_id or gen_id("wl"),
        name=a.wordlist_name or "听写",
        subject=subject,
        items=items,
    )


def pending_assignments(today: Optional[str] = None) -> list[DictationAssignment]:
    """返回截至 ``today`` 仍未完成的待办布置（due_date <= today 且 not done）。

    ``today`` 留空则用系统当前日期。这样教师今日布置（截止日=明日）不会立即显示在
    待办里，而次日课代表打开时即出现；过期未听写的也会持续显示在顶部提醒。
    """
    today = today or _today()
    return [a for a in list_assignments()
            if not a.done and (a.due_date or "") <= today]

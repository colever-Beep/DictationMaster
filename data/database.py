"""SQLite 数据层：历史记录 + 错题本（规范 §F4 / M5）。

使用标准库 ``sqlite3``，数据库文件位于 ``%LOCALAPPDATA%/DictationMaster/data/dictation.db``。
所有接口均为同步调用（数据量小，毫秒级），线程安全性由 sqlite3 连接级锁保证——
本模块所有操作都从 UI 主线程发起，无需额外加锁。

错题本语义（§F4）：
- 每个词条在听写中被标记为「写错」时，``record_wrong`` 使其计数 +1；
- 被标记为「已掌握」时，``mark_mastered`` 直接移除该词条（掌握即从错题本毕业）；
- 列表按错误次数降序排列。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

from core.paths import DB_FILE

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,          -- ISO 时间：会话开始时刻
    wordlist_name TEXT NOT NULL,       -- 词表名（快照，词表删除后仍可显示）
    subject TEXT NOT NULL DEFAULT '',  -- chinese / english
    word_count INTEGER NOT NULL,       -- 词条数
    duration_sec REAL NOT NULL,        -- 耗时（秒）
    accuracy REAL,                     -- 正确率 0~1；未标记完成为 NULL
    details TEXT NOT NULL DEFAULT '[]' -- JSON：[{text,alias,lang,status}, ...]
);
CREATE TABLE IF NOT EXISTS wrongbook (
    text TEXT PRIMARY KEY,             -- 词条文本（同文本合并计数）
    lang TEXT NOT NULL DEFAULT 'zh',
    wrong_count INTEGER NOT NULL DEFAULT 1,
    last_wrong_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """创建表结构（幂等）。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


# ------------------------------------------------------------------ 历史记录
def add_history(started_at: str, wordlist_name: str, subject: str,
                word_count: int, duration_sec: float,
                details: list[dict[str, Any]],
                accuracy: Optional[float] = None) -> int:
    """插入一条会话历史，返回记录 id。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO history(started_at, wordlist_name, subject, word_count,"
            " duration_sec, accuracy, details) VALUES(?,?,?,?,?,?,?)",
            (started_at, wordlist_name, subject, word_count, duration_sec,
             accuracy, json.dumps(details, ensure_ascii=False)))
        return int(cur.lastrowid or 0)


def update_history_result(hid: int, accuracy: Optional[float],
                          details: list[dict[str, Any]]) -> None:
    """用户在结果页完成标记后，回写正确率与明细。"""
    with _connect() as conn:
        conn.execute("UPDATE history SET accuracy=?, details=? WHERE id=?",
                     (accuracy, json.dumps(details, ensure_ascii=False), hid))


def list_history() -> list[dict[str, Any]]:
    """全部会话历史，按开始时间倒序。"""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM history ORDER BY started_at DESC, id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d.get("details") or "[]")
            except json.JSONDecodeError:
                d["details"] = []
            out.append(d)
        return out


def delete_history(hid: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM history WHERE id=?", (hid,))


def clear_history() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM history")


# ------------------------------------------------------------------ 错题本
def record_wrong(text: str, lang: str = "zh",
                 when: Optional[datetime] = None) -> None:
    """记一次写错：计数 +1（新词条自动插入）。"""
    ts = (when or datetime.now()).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO wrongbook(text, lang, wrong_count, last_wrong_at)"
            " VALUES(?,?,1,?)"
            " ON CONFLICT(text) DO UPDATE SET wrong_count=wrong_count+1,"
            " last_wrong_at=excluded.last_wrong_at, lang=excluded.lang",
            (text, lang, ts))


def mark_mastered(text: str) -> None:
    """标记掌握：从错题本移除。"""
    with _connect() as conn:
        conn.execute("DELETE FROM wrongbook WHERE text=?", (text,))


def list_wrong() -> list[dict[str, Any]]:
    """全部错词，按错误次数降序、其次按最近写错时间降序。"""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT text, lang, wrong_count, last_wrong_at FROM wrongbook"
            " ORDER BY wrong_count DESC, last_wrong_at DESC").fetchall()
        return [dict(r) for r in rows]


def clear_wrongbook() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM wrongbook")


# ------------------------------------------------------------------ 结果页明细工具
STATUS_UNSET = "未标记"
STATUS_WRONG = "写错"
STATUS_OK = "已掌握"


def apply_result_marks(details: list[dict[str, Any]]) -> dict[str, int]:
    """把结果页标记落库：写错 → 计数 +1；已掌握 → 移除错题。

    返回 ``{"wrong": n, "mastered": m}``。``details`` 为结果页的词状态列表，
    每项至少含 ``text`` / ``lang`` / ``status``。
    """
    wrong = mastered = 0
    now = datetime.now()
    for d in details:
        text = (d.get("text") or "").strip()
        if not text:
            continue
        status = d.get("status")
        if status == STATUS_WRONG:
            record_wrong(text, d.get("lang", "zh"), now)
            wrong += 1
        elif status == STATUS_OK:
            mark_mastered(text)
            mastered += 1
    return {"wrong": wrong, "mastered": mastered}

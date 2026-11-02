"""M5 复盘测试：SQLite 历史记录 / 错题本 + 结果页标记 / 重练 / 导出。"""

from __future__ import annotations

import csv
import importlib
import json
from datetime import datetime

import pytest

import core.paths as paths_mod
import data.repository as repo


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """把 database 模块内的 DB_FILE 指到临时文件。"""
    fake = tmp_path / "test.db"
    monkeypatch.setattr(paths_mod, "DB_FILE", fake)
    import data.database as db
    # database 用 `from core.paths import DB_FILE` 绑定，必须同时 patch 模块属性
    monkeypatch.setattr(db, "DB_FILE", fake)
    db.init_db()
    yield db


@pytest.fixture()
def isolated_repo(tmp_path, monkeypatch):
    """把词表目录指到临时目录。"""
    wl_dir = tmp_path / "wordlists"
    wl_dir.mkdir()
    monkeypatch.setattr(paths_mod, "WORDLISTS_DIR", wl_dir)
    import data.repository as repo_mod
    monkeypatch.setattr(repo_mod, "WORDLISTS_DIR", wl_dir)
    yield


# ------------------------------------------------------------------ 历史
def test_history_crud(isolated_db):
    db = isolated_db
    hid = db.add_history("2026-10-04T12:00:00", "测试词表", "chinese", 10, 123.5,
                         [{"text": "苹果", "lang": "zh"}])
    assert hid > 0
    rows = db.list_history()
    assert len(rows) == 1
    r = rows[0]
    assert r["wordlist_name"] == "测试词表"
    assert r["word_count"] == 10
    assert r["accuracy"] is None
    assert r["details"][0]["text"] == "苹果"

    db.update_history_result(hid, 0.8, [{"text": "苹果", "status": "已掌握"}])
    r = db.list_history()[0]
    assert r["accuracy"] == pytest.approx(0.8)
    assert r["details"][0]["status"] == "已掌握"

    db.delete_history(hid)
    assert db.list_history() == []


def test_history_order_and_clear(isolated_db):
    db = isolated_db
    db.add_history("2026-10-01T08:00:00", "早", "chinese", 5, 60, [])
    db.add_history("2026-10-03T09:00:00", "晚", "chinese", 5, 60, [])
    names = [r["wordlist_name"] for r in db.list_history()]
    assert names == ["晚", "早"]  # 倒序
    db.clear_history()
    assert db.list_history() == []


# ------------------------------------------------------------------ 错题本
def test_wrongbook_record_and_master(isolated_db):
    db = isolated_db
    db.record_wrong("苹果", "zh")
    db.record_wrong("苹果", "zh")
    db.record_wrong("banana", "en")
    rows = db.list_wrong()
    # 按错误次数降序
    assert rows[0]["text"] == "苹果"
    assert rows[0]["wrong_count"] == 2
    assert rows[1]["text"] == "banana"
    # 时间格式合法
    datetime.fromisoformat(rows[0]["last_wrong_at"])

    db.mark_mastered("苹果")
    rows = db.list_wrong()
    assert len(rows) == 1
    assert rows[0]["text"] == "banana"

    db.clear_wrongbook()
    assert db.list_wrong() == []


def test_apply_result_marks(isolated_db):
    db = isolated_db
    db.record_wrong("旧错词")           # 已在错题本
    details = [
        {"text": "新错词", "lang": "zh", "status": db.STATUS_WRONG},
        {"text": "旧错词", "lang": "zh", "status": db.STATUS_OK},  # 掌握 → 移除
        {"text": "没标记", "lang": "zh", "status": db.STATUS_UNSET},
    ]
    stats = db.apply_result_marks(details)
    assert stats == {"wrong": 1, "mastered": 1}
    texts = {r["text"] for r in db.list_wrong()}
    assert "新错词" in texts and "旧错词" not in texts


# ------------------------------------------------------------------ 结果页 UI
def test_result_page_marks_and_retrain(app, isolated_db, isolated_repo):
    from data.repository import get_wordlist, list_wordlists
    from ui.pages.dictation_page import DictationPage

    page = DictationPage(None)  # 无服务也能构建
    result = {
        "subject": "chinese",
        "total": 3,
        "words": [
            {"text": "苹果", "alias": "", "lang": "zh"},
            {"text": "香蕉", "alias": "", "lang": "zh"},
            {"text": "橘子", "alias": "júzi", "lang": "zh"},
        ],
    }
    page._last_cfg = None
    page._fill_result(result)
    assert page._result_table.rowCount() == 3

    # 标记：0→已掌握，1→写错，2→未标记
    page._result_table.cellWidget(0, 2).setCurrentText("已掌握")
    page._result_table.cellWidget(1, 2).setCurrentText("写错")
    marks = page._collect_marks()
    assert [m["status"] for m in marks] == ["已掌握", "写错", "未标记"]

    # 全部标记已掌握
    page._on_mark_all_mastered()
    assert all(m["status"] == "已掌握" for m in page._collect_marks())

    # 重练错词：把第 1 行标回写错
    page._result_table.cellWidget(0, 2).setCurrentText("写错")
    page._result_table.cellWidget(1, 2).setCurrentText("已掌握")
    page._last_result = result
    page._on_retrain_wrong()
    lists = list_wordlists()
    assert len(lists) == 1
    wl = get_wordlist(lists[0].id)
    assert wl.name.startswith("错词重练")
    assert [i.text for i in wl.items] == ["苹果"]

    # 清理
    from data.repository import delete_wordlist
    delete_wordlist(wl.id)


def test_wrongbook_and_history_pages_construct(app, isolated_db):
    from ui.pages.history_page import HistoryPage
    from ui.pages.wrongbook_page import WrongBookPage

    wb = WrongBookPage(None)
    wb.refresh()
    assert wb._table.columnCount() == 4

    hp = HistoryPage(None)
    hp.refresh()
    assert hp._table.columnCount() == 6

    # 写入数据后再刷新
    isolated_db.record_wrong("蝴蝶", "zh")
    isolated_db.add_history("2026-10-04T10:00:00", "测试", "chinese", 2, 30.0,
                            [{"text": "蝴蝶", "status": "写错"}], 0.5)
    wb.refresh()
    hp.refresh()
    assert wb._table.rowCount() == 1
    assert hp._table.rowCount() == 1
    # 正确率显示
    assert hp._table.item(0, 5).text() == "50%"

"""M3 词表层测试：仓储 CRUD / 导入解析 / 教材加载 / UI 构造。

测试使用临时目录，并通过 monkeypatch 把 ``data.repository`` 与 ``core.paths``
中的目录常量同时指向临时目录，避免污染用户真实数据。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import core.paths as paths_mod
import data.repository as repo


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    """把词表/教材/数据目录都指向临时目录。"""
    wl = tmp_path / "wordlists"
    tb = tmp_path / "textbooks"
    data = tmp_path / "data"
    for d in (wl, tb, data):
        d.mkdir(parents=True, exist_ok=True)
    # 同时改写 core.paths 与 data.repository 中已导入的常量
    monkeypatch.setattr(paths_mod, "WORDLISTS_DIR", wl)
    monkeypatch.setattr(paths_mod, "TEXTBOOKS_DIR", tb)
    monkeypatch.setattr(paths_mod, "DATA_DIR", data)
    monkeypatch.setattr(repo, "WORDLISTS_DIR", wl)
    monkeypatch.setattr(repo, "TEXTBOOKS_DIR", tb)
    monkeypatch.setattr(repo, "DATA_DIR", data)
    monkeypatch.setattr(repo, "PRESETS_FILE", data / "presets.json")
    return {"wl": wl, "tb": tb, "data": data}


def _sample_wl(name="测试表", subject="chinese", items=None):
    from data.models import WordItem, WordList
    from data.repository import gen_id
    items = items or [
        WordItem(id=gen_id("it"), text="苹果", alias="píng guǒ", lang="zh", enabled=True),
        WordItem(id=gen_id("it"), text="香蕉", alias="", lang="zh", enabled=True),
        WordItem(id=gen_id("it"), text="apple", alias="", lang="en", enabled=False),
    ]
    return WordList(id=gen_id("wl"), name=name, subject=subject, items=items)


# ----------------------------------------------------------------- 仓储 CRUD
def test_wordlist_crud(tmp_dirs):
    wl = _sample_wl()
    repo.save_wordlist(wl)
    assert repo.get_wordlist(wl.id) is not None
    assert repo.get_wordlist(wl.id).name == "测试表"

    listed = repo.list_wordlists()
    assert len(listed) == 1

    repo.rename_wordlist(wl.id, "改名了")
    assert repo.get_wordlist(wl.id).name == "改名了"

    copied = repo.copy_wordlist(wl.id)
    assert copied is not None and copied.id != wl.id
    assert len(repo.list_wordlists()) == 2

    repo.delete_wordlist(wl.id)
    assert repo.get_wordlist(wl.id) is None


def test_export_formats(tmp_dirs, tmp_path):
    wl = _sample_wl()
    txt = tmp_path / "a.txt"
    csvf = tmp_path / "b.csv"
    assert repo.export_wordlist(wl, str(txt)) == "txt"
    assert repo.export_wordlist(wl, str(csvf)) == "csv"
    assert "苹果" in txt.read_text(encoding="utf-8-sig")
    lines = csvf.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("text,alias")  # 表头


def test_estimate_seconds():
    from data.models import WordItem, WordList
    from data.repository import gen_id
    wl = WordList(id="x", name="x", subject="chinese", items=[
        WordItem(id=gen_id("it"), text="一二三四五六七八", lang="zh"),
    ])
    secs = repo.estimate_seconds(wl, repeat=2, interval=10, inner_pause=1.5)
    # 8 字 * 0.35 + 1.5*1 + 10 ≈ 14.3s
    assert 13 < secs < 16


# ----------------------------------------------------------------- 导入解析
def test_parse_txt(tmp_path):
    from ui.dialogs.import_dialog import parse_file
    p = tmp_path / "w.txt"
    p.write_text("苹果\n香蕉\n\n橘子", encoding="utf-8")
    rows = parse_file(str(p))
    assert [r[0] for r in rows] == ["苹果", "香蕉", "橘子"]


def test_parse_csv(tmp_path):
    from ui.dialogs.import_dialog import parse_file
    p = tmp_path / "w.csv"
    p.write_text("苹果,pingguo\n香蕉,\n", encoding="utf-8-sig")
    rows = parse_file(str(p))
    assert rows[0] == ["苹果", "pingguo"]
    assert rows[1] == ["香蕉", ""]


def _make_xlsx(path: Path, values: list[list[str]]) -> None:
    """构造一个最小可用 xlsx（含 sharedStrings + 单工作表）。"""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    # 有序去重，保证 sharedStrings 与索引一致
    uniq: list[str] = []
    for row in values:
        for c in row:
            if c not in uniq:
                uniq.append(c)
    index = {v: i for i, v in enumerate(uniq)}
    shared = "".join(f'<si><t xml:space="preserve">{v}</t></si>' for v in uniq)
    sheets = "".join(
        f'<row r="{i+1}">' + "".join(
            f'<c r="{chr(65+c)}" t="s"><v>{index[val]}</v></c>'
            for c, val in enumerate(row)) + '</row>'
        for i, row in enumerate(values))
    content_types = ('<?xml version="1.0"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wb = ('<?xml version="1.0"?><workbook xmlns="%s"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % ns)
    wb_rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
               '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/sharedStrings.xml",
                    f'<?xml version="1.0"?><sst xmlns="{ns}">{shared}</sst>')
        zf.writestr("xl/worksheets/sheet1.xml",
                    f'<?xml version="1.0"?><worksheet xmlns="{ns}">{sheets}</worksheet>')


def test_parse_xlsx(tmp_path):
    from ui.dialogs.import_dialog import parse_file
    p = tmp_path / "w.xlsx"
    _make_xlsx(p, [["苹果", "pingguo"], ["香蕉", "xiangjiao"]])
    rows = parse_file(str(p))
    assert rows[0] == ["苹果", "pingguo"]
    assert rows[1] == ["香蕉", "xiangjiao"]


# ----------------------------------------------------------------- 教材加载
def test_textbook_loading(tmp_dirs):
    tb = tmp_dirs["tb"] / "小学语文_测试.json"
    tb.write_text(
        '{"subject":"chinese","stage":"小学","grade":"三年级","volume":"上册",'
        '"units":[{"name":"第一单元","words":["春","夏","秋","冬"]},'
        '{"name":"第二单元","words":["风","雨"]}]}', encoding="utf-8")
    metas = repo.list_textbooks()
    assert len(metas) == 1
    units = repo.get_textbook_units(metas[0])
    assert units == ["第一单元", "第二单元"]
    words = repo.load_textbook_words(metas[0], "第一单元")
    assert words == ["春", "夏", "秋", "冬"]


# ----------------------------------------------------------------- UI 构造
def test_wordlist_page_construct(app):
    from ui.pages.wordlist_page import WordListPage
    page = WordListPage(services=None)
    assert page is not None
    page._reload()
    # 左侧已改为可折叠「词表子导航抽屉」，含分组（自建 / 默认教材·小学·初中·高中）
    assert page.drawer is not None
    # 抽屉至少包含一个分组标题
    assert len(page._drawer_groups) >= 2
    # 抽屉默认展开，且能折叠/展开
    assert page.drawer.selected_id() is not None
    page.drawer.set_collapsed(True, animate=False)
    assert page.drawer._collapsed is True
    page.drawer.set_collapsed(False, animate=False)
    assert page.drawer._collapsed is False
    # 右侧词卡网格：选中词表后应渲染出词卡
    assert page.card_layout.count() > 0


def test_wordlist_drawer_displays_wordlist_name(app):
    from ui.widgets.wordlist_drawer import NavItemButton

    wl = _sample_wl(name="我的词表名称")
    button = NavItemButton(wl)

    assert button.name_label.text() == wl.name


def test_wordlist_page_removes_old_cards_on_selection(app):
    from ui.pages.wordlist_page import WordListPage

    page = WordListPage(services=None)
    first = _sample_wl(name="第一份", items=_sample_wl().items[:1])
    second = _sample_wl(name="第二份", items=_sample_wl().items[:2])

    page._render_cards(first)
    old_card = page.card_layout.itemAt(0).widget()
    page._render_cards(second)

    assert page.card_layout.count() == len(second.items)
    assert old_card.isHidden()


def test_editor_dialog_construct(app):
    from data.models import WordList
    from data.repository import gen_id
    from PySide6.QtWidgets import QWidget
    from ui.dialogs.wordlist_editor import WordListEditorDialog
    wl = WordList(id=gen_id("wl"), name="构造测试", subject="chinese", items=[])
    # MaskDialogBase 需要非 None 的 parent（会读取 parent.width()）
    parent = QWidget()
    dlg = WordListEditorDialog(parent, None, wl)
    assert dlg._table is not None
    dlg._refresh_stats()  # 不抛异常即可

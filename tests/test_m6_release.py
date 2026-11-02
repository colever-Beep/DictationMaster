"""M6 发布测试：设置页 F5 分组 / 首启引导对话框 / 图标与打包配置自检。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ 设置页
def test_setting_page_groups(app):
    from ui.pages.setting_page import SettingPage

    page = SettingPage(None)
    # 五组卡片：通用 / 语音 / 存储 / 快捷键 / 关于
    assert page.body.count() >= 5
    # 自定义音色下拉已填充内置音色（服务为空时回退 builtin）
    assert page._zh_combo.count() > 0
    assert page._en_combo.count() > 0
    # 默认选中项是配置里的默认音色
    assert page._zh_combo.currentData() == "zh-CN-XiaoxiaoNeural"


def test_setting_page_cache_size_refresh(app, tmp_path):
    from ui.pages.setting_page import SettingPage

    page = SettingPage(None)
    # 指向空目录刷新不抛异常且显示 0 B
    page._services = type("S", (), {"tts": type("T", (), {"cache_dir": lambda s: tmp_path})()})()
    page.refresh_cache_size()
    assert "0 B" in page._size_label.text()


def test_voice_connectivity_test_wiring(app, monkeypatch):
    """M6 补充：设置页「测试语音」按钮与「试听」本地直合成分支接线正确（不依赖网络）。"""
    from ui.pages.setting_page import SettingPage, _SynthWorker

    # 用桩替换真实合成线程，仅验证接线
    calls = []
    monkeypatch.setattr(_SynthWorker, "start", lambda self: calls.append(self))

    page = SettingPage(None)
    # 语音组新增「测试语音」按钮，且「试听」按钮存在
    assert page._test_card.button.text() == "测试语音"
    assert page._preview_card.button.text() == "试听"

    # 触发「测试语音」：应启动一个合成 worker 并置忙
    page._busy = False
    page._on_test_voice()
    assert page._busy is True
    assert len(calls) == 1

    # 设置页未注入 services 时，试听走本地直合成分支（不应抛异常）
    page._busy = False
    page.on_preview_clicked()
    assert len(calls) == 2


# ------------------------------------------------------------------ 首启引导
def test_first_run_dialog_steps(app):
    from ui.dialogs.first_run import FirstRunDialog

    host = QWidget()
    dlg = FirstRunDialog(host)
    assert dlg._pages.count() == 3
    # 初始在第 0 步，「上一步」禁用
    assert dlg._step == 0
    assert not dlg._prev_btn.isEnabled()
    # 走到最后一步后按钮变「完成」
    dlg._on_next()
    dlg._on_next()
    assert dlg._step == 2
    assert dlg._next_btn.text() == "完成"
    # 结果默认值合法
    r = dlg.result()
    assert r["subject"] in ("chinese", "english")
    assert r["wordlist_name"] == ""
    assert r["words"] == []


def test_first_run_dialog_textbook_import(app, monkeypatch):
    from ui.dialogs.first_run import FirstRunDialog

    host = QWidget()
    dlg = FirstRunDialog(host)

    fake = {"name": "三年级上 · 第一单元", "subject": "english",
            "words": ["apple", "banana"]}
    import ui.dialogs.textbook_picker as tp
    monkeypatch.setattr(tp.TextbookPickerDialog, "get_selection",
                        staticmethod(lambda parent: fake))
    dlg._on_import_textbook()
    assert dlg._name_edit.text() == "三年级上 · 第一单元"
    assert dlg.result()["words"] == ["apple", "banana"]
    assert dlg.result()["subject"] == "english"


# ------------------------------------------------------------------ 打包自检
def test_icon_exists_and_readable():
    ico = ROOT / "assets" / "app.ico"
    assert ico.exists() and ico.stat().st_size > 1000
    icon = QIcon(str(ico))
    sizes = icon.availableSizes()
    assert len(sizes) >= 5          # 多尺寸
    assert not icon.pixmap(256, 256).isNull()


def test_packaging_files_present():
    assert (ROOT / "app.spec").exists()
    spec = (ROOT / "app.spec").read_text(encoding="utf-8")
    for pkg in ("PySide6", "qfluentwidgets", "edge_tts"):
        assert pkg in spec
    assert 'collect_all(_pkg)' in spec
    assert "assets/app.ico" in spec
    assert (ROOT / "build.bat").exists()
    assert "multimedia" in (ROOT / "build.bat").read_text(encoding="utf-8")
    assert (ROOT / "README.md").exists()


def test_textbooks_datas_exist():
    # app.spec 打包了 data/textbooks，目录至少要有内置示例
    books = list((ROOT / "data" / "textbooks").glob("*.json"))
    assert len(books) >= 2


# ------------------------------------------------------------------ 听写前选词对话框
def test_word_selection_dialog(app):
    from ui.dialogs.word_selection_dialog import WordSelectionDialog
    from data.models import WordItem, WordList

    host = QWidget()
    host.resize(900, 600)
    host.show()

    wl = WordList(
        id="wl_sel", name="选词测试", subject="english",
        items=[WordItem(id=f"it{i}", text=f"w{i}", alias="", lang="en",
                        note=f"note{i}")
               for i in range(10)])
    dlg = WordSelectionDialog(wl, host)
    dlg.show()

    assert len(dlg._grid._checks) == 10
    assert len(dlg.selected_items()) == 10

    # 取消勾选第 0/5 项
    dlg._grid._checks[0][0].setChecked(False)
    dlg._grid._checks[5][0].setChecked(False)
    assert len(dlg.selected_items()) == 8

    # 反选
    dlg._grid._invert()
    assert len(dlg.selected_items()) == 2

    # 清空
    dlg._grid._clear_all()
    assert len(dlg.selected_items()) == 0

    # 全选
    dlg._grid._select_all()
    assert len(dlg.selected_items()) == 10


# ------------------------------------------------------------------ 听写布置：跨机自包含
def test_assignment_export_import_roundtrip(tmp_path, monkeypatch):
    """教师办公室布置 → 导出文件 → 课代表一体机导入，且无需原词表即可还原。

    用 monkeypatch 把 assignments 目录分别指向「办公室」「教室」两个临时目录，
    全程不删除任何文件（规避沙箱批量删除守卫 WinError 6 的干扰）。
    """
    import data.assignments_repo as R
    from data.models import DictationAssignment

    office_dir = tmp_path / "office"
    class_dir = tmp_path / "classroom"
    office_dir.mkdir()
    class_dir.mkdir()

    # 1) 办公室电脑：保存布置
    monkeypatch.setattr(R, "ASSIGNMENTS_DIR", office_dir)
    asg = DictationAssignment(
        id="asg_office", name="10月8日 听写 · Unit1", wordlist_id="wl_xxx",
        wordlist_name="人教版必修一 Unit1", subject="english",
        selected_ids=["it1", "it3"],
        words=[
            {"id": "it1", "text": "exchange", "alias": "", "lang": "en", "note": "交换"},
            {"id": "it3", "text": "register", "alias": "", "lang": "en", "note": "注册"},
        ],
        config={"subject": "english", "repeat": 2, "interval": 10,
                "inner_pause": 1.5, "rate": "-10%", "volume": "+0%", "pitch": "+0Hz",
                "shuffle": False, "loop": False, "countdown_beep": True,
                "word_beep": False, "end_beep": True, "paper_mode": True,
                "show_answer_at_end": True, "voices": ["en-US-AriaNeural"],
                "concurrency": 4, "seed": None},
        due_date="2026-10-08",
    )
    R.save_assignment(asg)
    assert len(R.pending_assignments("2026-10-08")) == 1

    # 2) 导出文件（自包含，含 words）
    fpath = tmp_path / "task.dictation-task.json"
    R.export_assignment_file(asg, str(fpath))
    assert fpath.exists() and fpath.stat().st_size > 0

    # 3) 教室一体机：导入（指向另一个空目录，模拟不同机器）
    monkeypatch.setattr(R, "ASSIGNMENTS_DIR", class_dir)
    assert len(R.list_assignments()) == 0
    imp = R.import_assignment_file(str(fpath))
    assert imp.id != asg.id            # 导入重新生成 id，避免冲突
    assert len(R.pending_assignments("2026-10-08")) == 1

    # 4) 关键：原词表 wl_xxx 不存在，但凭自带 words 仍能还原听写词表
    wl = R.build_wordlist_from_assignment(imp)
    assert wl.subject == "english"
    assert [w.text for w in wl.items] == ["exchange", "register"]


def test_assignment_start_uses_bundled_words():
    """还原听写词表应优先用自带 words，不依赖原词表（跨机场景）。"""
    from data.models import DictationAssignment, WordList
    from data.assignments_repo import build_wordlist_from_assignment

    a = DictationAssignment(
        id="asg_x", name="t", wordlist_id="nonexistent_wl", wordlist_name="某词表",
        subject="english", words=[{"id": "k1", "text": "apple", "lang": "en"}],
        config={}, due_date="2026-10-08",
    )
    # 与页面 _on_start_assignment 复用同一还原函数
    wl = build_wordlist_from_assignment(a)
    assert isinstance(wl, WordList)
    assert wl.items[0].text == "apple"



# ------------------------------------------------------------------ 主题标签：浅色模式不白字
def test_dictation_labels_theme_aware(app):
    from ui.pages.dictation_page import DictationPage
    from qfluentwidgets import isDarkTheme

    page = DictationPage()
    expected_color = "#FFFFFF" if isDarkTheme() else "#1A1A1A"
    assert expected_color in page._center.styleSheet()
    assert expected_color in page._big.styleSheet()


# ------------------------------------------------------------------ 配置持久化（首启引导不应每次弹出）
def test_config_persists_across_reload(tmp_path, monkeypatch):
    """qconfig.load 必须把自定义 cfg 绑定进去，否则配置不落盘。

    复现并锁定「首次启动引导每次都弹」的根因：load 时未传 config=cfg，
    导致 qconfig 只读写内置单例、cfg 上的 first_run_done 等项永不持久化。
    """
    import qfluentwidgets
    from app_config import Config

    qc = qfluentwidgets.qconfig
    saved_cfg = qc._cfg
    saved_file = qc.file
    try:
        f = tmp_path / "config.json"
        c = Config()
        qc.load(file=str(f), config=c)      # 修复后的正确用法
        c.first_run_done.value = True
        c.subject.value = "english"
        qc.save()

        # 模拟「再次启动」：全新的 Config 实例从同一文件加载
        c2 = Config()
        qc.load(file=str(f), config=c2)
        assert c2.first_run_done.value is True
        assert c2.subject.value == "english"
    finally:
        qc._cfg = saved_cfg
        qc.file = saved_file


def test_init_config_binds_cfg(monkeypatch, tmp_path):
    """init_config() 必须把 cfg 绑定到 qconfig，否则设置不生效。"""
    import qfluentwidgets
    import app_config
    from core import paths

    tmp = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "CONFIG_FILE", tmp)
    monkeypatch.setattr(paths, "CONFIG_FILE", tmp)

    saved = (qfluentwidgets.qconfig._cfg, qfluentwidgets.qconfig.file,
             app_config.cfg.first_run_done.value)
    try:
        app_config.init_config()
        # 关键断言：qconfig 内部已指向我们的 cfg 实例
        assert qfluentwidgets.qconfig._cfg is app_config.cfg
    finally:
        qfluentwidgets.qconfig._cfg, qfluentwidgets.qconfig.file = saved[0], saved[1]
        app_config.cfg.first_run_done.value = saved[2]


# ------------------------------------------------------------------ 词表内置/年级分类
def test_wordlist_builtin_grade_serialization():
    """WordList 的 builtin/grade 字段应能正确序列化与还原。"""
    from data.models import WordList, WordItem
    from data.repository import wordlist_to_dict, wordlist_from_dict

    wl = WordList(id="x", name="n", subject="english", builtin=True, grade="高中",
                  items=[WordItem(id="i", text="hi")])
    d = wordlist_to_dict(wl)
    assert d["builtin"] is True and d["grade"] == "高中"
    back = wordlist_from_dict(d)
    assert back.builtin is True and back.grade == "高中"


def test_copy_wordlist_drops_builtin(tmp_path, monkeypatch):
    """复制内置词表产生的副本应归用户所有（builtin=False），但保留年级信息。"""
    import data.repository as R
    from data.models import WordList, WordItem

    monkeypatch.setattr(R, "WORDLISTS_DIR", tmp_path)
    src = WordList(id="s", name="s", subject="english", builtin=True, grade="高中",
                   items=[WordItem(id="i", text="hi")])
    R.save_wordlist(src)
    new = R.copy_wordlist("s")
    assert new.builtin is False
    assert new.grade == "高中"


def test_editor_preserves_builtin_grade(app):
    """编辑已有内置词表时，不应丢失 builtin/grade 属性。"""
    from PySide6.QtWidgets import QWidget
    from ui.dialogs.wordlist_editor import WordListEditorDialog
    from data.models import WordList, WordItem

    host = QWidget()
    wl = WordList(id="b", name="内置表", subject="english", builtin=True, grade="高中",
                  items=[WordItem(id="i", text="hi")])
    dlg = WordListEditorDialog(host, None, wl)
    assert dlg._wl.builtin is True
    assert dlg._wl.grade == "高中"


def test_wordlist_page_groups_by_builtin_grade(app, monkeypatch, tmp_path):
    """词表页左侧应分为「自建词表 / 默认教材词表→小学·初中·高中」。"""
    import data.repository as R
    from data.models import WordList, WordItem
    from ui.pages.wordlist_page import WordListPage

    monkeypatch.setattr(R, "WORDLISTS_DIR", tmp_path)
    R.save_wordlist(WordList(id="u1", name="我的词表", subject="chinese",
                             items=[WordItem(id="i", text="你")]))
    R.save_wordlist(WordList(id="p1", name="必修一U1", subject="english",
                             builtin=True, grade="高中",
                             items=[WordItem(id="i", text="hello")]))

    page = WordListPage()
    groups = {name: wls for name, wls in page._drawer_groups}
    # 自建词表分组
    assert "自建词表" in groups
    assert len(groups["自建词表"]) == 1
    assert groups["自建词表"][0].id == "u1"
    # 默认教材按年级分组的「高中」组含有内置词表
    assert "默认教材 · 高中" in groups
    assert len(groups["默认教材 · 高中"]) == 1
    assert groups["默认教材 · 高中"][0].id == "p1"
    # 其它年级分组存在但为空
    assert groups["默认教材 · 小学"] == []
    assert groups["默认教材 · 初中"] == []
    assert groups["默认教材 · 高中"][0].name == "必修一U1"

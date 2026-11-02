"""听前信息确认弹窗单元测试：纯函数摘要 + 弹窗可构造。

不依赖真实网络/音频；``build_session_summary`` 为纯函数，便于无头单测。
"""

from __future__ import annotations

from core.dictation_engine import PlayConfig, estimate_dictation_minutes
from data.models import WordItem, WordList
from ui.dialogs.pre_dictation_dialog import (
    PreDictationDialog,
    build_session_summary,
)


def _wl(n: int = 3) -> WordList:
    return WordList(
        id="w", name="测试词表", subject="chinese",
        items=[WordItem(id=f"it{i}", text=f"词{i}", lang="zh") for i in range(n)],
    )


def test_build_session_summary_keeps_only_six_fields():
    cfg = PlayConfig(subject="chinese", repeat=2, interval=10, inner_pause=1.5,
                     shuffle=True, loop=False, countdown_beep=True,
                     word_beep=False, end_beep=True, announce=True,
                     paper_mode=True, voices=["zh-CN-XiaoxiaoNeural"],
                     rate="-10%", volume="+0%", pitch="+0Hz")
    pairs = build_session_summary(_wl(5), cfg)
    keys = [k for k, _ in pairs]
    assert keys == ["学科", "词表", "词语数量", "朗读次数", "书写时间", "预计时长"]
    d = dict(pairs)
    assert d["学科"] == "语文"
    assert d["词表"] == "测试词表"
    assert d["词语数量"] == "5 个"
    assert d["朗读次数"] == "2 遍"
    assert d["书写时间"] == "10 秒/词"
    assert d["预计时长"].startswith("约")


def test_summary_english_subject():
    cfg = PlayConfig(subject="english", announce=False)
    d = dict(build_session_summary(_wl(1), cfg))
    assert d["学科"] == "英语"
    assert d["词语数量"] == "1 个"
    # 已精简掉音色/播报/乱序等冗余项
    assert "使用音色" not in d
    assert "听写信息播报" not in d


def test_estimate_minutes_positive():
    # 1 词 2 遍 10 秒书写 → 必然 >=1 分钟（与开场播报一致）
    assert estimate_dictation_minutes(1, 2, 1.5, 10) >= 1
    assert estimate_dictation_minutes(10, 3, 1.5, 10) > 1


def test_dialog_constructs_and_accept(app):
    import time

    from PySide6.QtWidgets import QApplication, QDialog

    cfg = PlayConfig(subject="chinese", repeat=2, interval=10)
    dlg = PreDictationDialog(_wl(3), cfg, None)
    # 弹窗可在 offscreen 下正常构造；accept 后 MaskDialogBase 有 100ms 淡出动画，
    # 结束后才真正 done() 并写入 result，这里泵事件直至拿到 Accepted。
    dlg.accept()
    for _ in range(40):
        QApplication.processEvents()
        if dlg.result() == QDialog.DialogCode.Accepted:
            break
        time.sleep(0.01)
    assert dlg.result() == QDialog.DialogCode.Accepted

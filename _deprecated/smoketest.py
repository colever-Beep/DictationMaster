"""离线冒烟测试：验证导入、图标渲染、窗口可构建（无显示）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def check():
    from ui.fluent import FluentWindow, set_theme
    from ui.icons import svg_icon
    from core.config import Config
    from ui.home import HomeInterface
    from ui.settings import SettingsInterface
    from ui.about import AboutInterface

    app = QApplication(sys.argv)
    set_theme(app, False)

    # 图标渲染
    for name in ["play", "pause", "stop", "next", "prev", "folder", "mic", "sync",
                 "copy", "history", "brush", "home", "settings", "info", "sun", "moon"]:
        ic = svg_icon(name, "#000000")
        assert not ic.isNull(), f"icon {name} null"

    config = Config()
    win = FluentWindow()
    home = HomeInterface(config)
    settings = SettingsInterface(config)
    about = AboutInterface()
    win.add_page(home, "home", "听写")
    win.add_page(settings, "settings", "设置")
    win.add_page(about, "info", "关于")
    win.resize(980, 700)
    win.show()
    app.processEvents()

    # 切换主题并重绘
    set_theme(app, True)
    app.processEvents()
    set_theme(app, False)

    pm = win.grab()
    assert not pm.isNull() and pm.width() > 0, "grab failed"

    # 播放器/生成器构造
    home.player.load([("x.mp3", 0)])
    print("pages:", win.stack.count(), "grab:", pm.width(), "x", pm.height())
    return True


if __name__ == "__main__":
    try:
        check()
        print("RESULT: PASS")
    except Exception:
        import traceback
        traceback.print_exc()
        print("RESULT: ERROR")
        sys.exit(1)

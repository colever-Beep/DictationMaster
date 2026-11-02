"""基于 qfluentwidgets 的 Fluent 风格封装：主题管理 + 主窗口。

qfluentwidgets 的 PySide6 版（PyPI 包名 PySide6-Fluent-Widgets）已自带
FluentWindow / FluentIcon / 各类 Fluent 控件与主题系统，本模块仅做轻量封装，
供 main.py 与各页面统一引用。
"""
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentWindow, FluentIcon, NavigationItemPosition, NavigationPushButton,
    setTheme, Theme, qconfig,
)


def is_dark() -> bool:
    """返回当前是否为深色主题。"""
    return qconfig.theme == Theme.DARK


def set_app_theme(dark: bool):
    setTheme(Theme.DARK if dark else Theme.LIGHT)


class AppWindow(FluentWindow):
    """主窗口：左侧导航 + 多页面 + 底部主题切换按钮。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Edge-TTS 听写")
        self.resize(1000, 720)

        # 底部主题切换按钮
        self.themeButton = NavigationPushButton(FluentIcon.BRIGHTNESS, "主题", False)
        self.themeButton.clicked.connect(self._toggle_theme)
        self.navigationInterface.addWidget(NavigationItemPosition.BOTTOM, self.themeButton)

        self._theme_callback = None

    def add_page(self, widget: QWidget, icon, text: str, name: str = None,
                 position=NavigationItemPosition.TOP):
        widget.setObjectName(name or text)
        self.addSubInterface(widget, icon, text, position)
        return widget

    def _toggle_theme(self):
        new_dark = not is_dark()
        set_app_theme(new_dark)
        if self._theme_callback:
            self._theme_callback(new_dark)

    def on_theme_changed(self, cb):
        self._theme_callback = cb

"""主窗口：基于 qfluentwidgets 的 MSFluentWindow，承载六个导航页面。

导航结构（规范 §3.1）：
  TOP    : 听写 / 我的词表 / 错题本 / 历史记录
  SCROLL : 设置
  BOTTOM : 关于

注意：addSubInterface 没有 routeKey 参数，路由键就是 interface.objectName()，
因此必须先 setObjectName 再添加；position 必须用关键字传参。
"""

from __future__ import annotations

from qfluentwidgets import MSFluentWindow, FluentIcon, NavigationItemPosition

from ui.dialogs.base import msg_confirm
from ui.pages.dictation_page import DictationPage
from ui.pages.wordlist_page import WordListPage
from ui.pages.wrongbook_page import WrongBookPage
from ui.pages.history_page import HistoryPage
from ui.pages.setting_page import SettingPage
from ui.pages.about_page import AboutPage


class MainWindow(MSFluentWindow):
    """听写助手主窗口。"""

    def __init__(self, services) -> None:
        super().__init__()
        self.setWindowTitle("听写助手")
        self.resize(1000, 720)
        # 不开启 Mica：窗口材质跟随系统会与应用内主题切换打架
        self.setMicaEffectEnabled(False)

        self._services = services
        self._init_pages()
        self._init_navigation()
        self._init_session_guard()

    def _init_session_guard(self) -> None:
        """听写进行中切换页面 / 关闭窗口需二次确认（规范 §F3 状态安全）。"""
        # 导航切换二次确认（信号名随版本可能不同，缺失则跳过）
        try:
            self.currentInterfaceChanged.connect(self._on_nav_changed)
        except Exception:  # noqa: BLE001
            pass

    def _on_nav_changed(self, widget) -> None:
        try:
            if widget is self.dictation_page or not self.dictation_page.is_session_active():
                return
            if not msg_confirm(
                self, "听写进行中",
                "正在听写，切换到其它页面将停止本次听写。确定切换？",
            ):
                if hasattr(self, "switchTo"):
                    self.switchTo(self.dictation_page)
            else:
                self.dictation_page.stop_session()
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:
        if self.dictation_page.is_session_active():
            if not msg_confirm(
                self, "听写进行中",
                "当前正在听写，退出将停止本次听写。确定退出？",
            ):
                event.ignore()
                return
            self.dictation_page.stop_session()
        try:
            self._services.shutdown()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)

    def _init_pages(self) -> None:
        self.dictation_page = DictationPage(self._services)
        self.wordlist_page = WordListPage(self._services)
        self.wrongbook_page = WrongBookPage(self._services)
        self.history_page = HistoryPage(self._services)
        self.setting_page = SettingPage(self._services)
        self.about_page = AboutPage()

    def _init_navigation(self) -> None:
        # (页面, 图标, 标题, routeKey, 位置)
        pages = [
            (self.dictation_page, FluentIcon.EDIT, "听写", "dictation", NavigationItemPosition.TOP),
            (self.wordlist_page, FluentIcon.LIBRARY, "我的词表", "wordlist", NavigationItemPosition.TOP),
            (self.wrongbook_page, FluentIcon.TAG, "错题本", "wrongbook", NavigationItemPosition.TOP),
            (self.history_page, FluentIcon.HISTORY, "历史记录", "history", NavigationItemPosition.TOP),
            (self.setting_page, FluentIcon.SETTING, "设置", "setting", NavigationItemPosition.SCROLL),
            (self.about_page, FluentIcon.INFO, "关于", "about", NavigationItemPosition.BOTTOM),
        ]
        for widget, icon, title, route_key, position in pages:
            # 先设 objectName，再 addSubInterface（routeKey 即 objectName）
            widget.setObjectName(route_key)
            self.addSubInterface(widget, icon, title, position=position)

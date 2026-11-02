"""页面基类与里程碑占位页辅助。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSpacerItem,
    QSizePolicy,
)

from qfluentwidgets import TitleLabel, BodyLabel, CardWidget, ScrollArea

from ui.widgets.theme_qss import style_page


class PageBase(QWidget):
    """功能页基类：统一的内容容器（标题 + 可滚动主体 + 底部弹性留白）。

    主体放在一个 ``ScrollArea`` 中，内容超出窗口高度时自动滚动；
    ``enableTransparentBackground()`` 让滚动区透明，避免原生 QScrollArea 视口
    在深色/浅色主题下回退成黑/深灰底（qfluentwidgets 已知坑）。
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        self.title_label = TitleLabel(title, self)
        outer.addWidget(self.title_label)

        # 可滚动主体
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setViewportMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll, 1)

        self.scroll_widget = QWidget()
        self.body = QVBoxLayout(self.scroll_widget)
        self.body.setSpacing(12)
        self.scroll.setWidget(self.scroll_widget)
        self.scroll.enableTransparentBackground()
        style_page(self)  # 页面根容器套主题背景，杜绝子控件透明透出黑底

    def add_widget(self, w: QWidget) -> None:
        """向页面主体追加一个控件（通常是 CardWidget）。"""
        self.body.addWidget(w)


class PlaceholderPage(PageBase):
    """里程碑占位页：用卡片说明该模块将在哪个里程碑实现。"""

    def __init__(self, title: str, milestone: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        card = CardWidget(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.addWidget(BodyLabel(f"本页面为占位，计划在 {milestone} 实现。"))
        cl.addWidget(
            BodyLabel("当前里程碑 M1 仅搭建骨架（窗口 / 导航 / 主题 / 日志 / 单实例）。")
        )
        self.add_widget(card)

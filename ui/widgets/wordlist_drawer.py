"""词表子导航抽屉（可折叠的左侧导航栏）。

- 词表按「自建词表 / 默认教材词表 → 小学·初中·高中」分组罗列。
- 支持抽屉化展开/收起：点击顶部按钮在「展开(显示名称+学科·词数)」与
  「收起(仅图标)」之间平滑切换，整条导航栏宽度动画过渡。
- 点击某词表通过 ``selected`` 信号把词表 id 抛给页面；页面据此在右侧
  以卡片方式罗列词汇。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon, ToolButton, isDarkTheme, themeColor

from data.models import WordList

EXPANDED_WIDTH = 280
COLLAPSED_WIDTH = 60


def _tint(color: QColor, alpha: int) -> QColor:
    """返回带透明度的同色。"""
    return QColor(color.red(), color.green(), color.blue(), alpha)


class NavItemButton(QFrame):
    """抽屉中的单个词表导航项（图标 + 名称 + 学科·词数）。

    选中态有左侧主题色指示条与浅色主题色背景；悬停有浅灰背景。
    收起态仅显示图标并居中。
    """

    clicked = Signal(str)  # 词表 id

    def __init__(self, wl: WordList, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wl = wl
        self._active = False
        self._hover = False
        self._collapsed = False
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.move(20, 10)

        self.name_label = QLabel(self)
        self.name_label.setObjectName("navName")
        self.name_label.setText(wl.name)
        subj = "英语" if wl.subject == "english" else "语文"
        self.meta_label = QLabel(f"{subj} · {len(wl.items)} 词", self)
        self.meta_label.setObjectName("navMeta")

        self._layout_labels()
        self._apply_theme()
        self.setToolTip(f"{wl.name}\n{subj}　{len(wl.items)} 词")

    # ----------------------------------------------------------- 布局
    def _layout_labels(self) -> None:
        label_width = max(0, self.width() - 56)
        self.name_label.setGeometry(48, 4, label_width, 18)
        self.meta_label.setGeometry(48, 21, label_width, 15)
        self.name_label.setText(
            QFontMetrics(self.name_label.font()).elidedText(
                self._wl.name, Qt.TextElideMode.ElideRight, label_width))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_labels()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        if collapsed:
            self.name_label.hide()
            self.meta_label.hide()
            self.icon_label.move(20, 10)  # 居中于 60 宽按钮
        else:
            self.name_label.show()
            self.meta_label.show()
            self.icon_label.move(20, 10)
        self.update()

    # ----------------------------------------------------------- 主题
    def _apply_theme(self) -> None:
        dark = isDarkTheme()
        name_color = "#1A1A1A" if not dark else "#FFFFFF"
        meta_color = "#737373" if not dark else "#A6A6A6"
        self.name_label.setStyleSheet(f"color: {name_color}; font-size: 13px;")
        self.meta_label.setStyleSheet(f"color: {meta_color}; font-size: 11px;")
        icon_color = QColor(0, 0, 0) if not dark else QColor(255, 255, 255)
        pix = (FluentIcon.LIBRARY if self._wl.builtin else FluentIcon.EDIT
               ).icon(color=icon_color).pixmap(18, 18)
        self.icon_label.setPixmap(pix)
        self.update()

    def refresh_theme(self) -> None:
        self._apply_theme()

    # ----------------------------------------------------------- 状态
    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, _e) -> None:
        self.clicked.emit(self._wl.id)

    # ----------------------------------------------------------- 绘制
    def paintEvent(self, _e) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        c = 255 if dark else 0
        rect = self.rect().adjusted(2, 2, -2, -2)
        if self._active:
            tint = _tint(themeColor(), 30 if not dark else 50)
            painter.setBrush(tint)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 6, 6)
            # 左侧主题色指示条
            painter.setBrush(themeColor())
            painter.drawRoundedRect(4, 10, 3, self.height() - 20, 1.5, 1.5)
        elif self._hover:
            painter.setBrush(QColor(c, c, c, 14 if not dark else 20))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 6, 6)


class WordListDrawer(QWidget):
    """可折叠的词表子导航抽屉。

    ``set_wordlists(groups)`` 重建分组列表；``filter(kw)`` 按名称过滤；
    ``select(id)`` 高亮并触发 ``selected``；``toggle()`` 在展开/收起间切换。
    """

    selected = Signal(str)  # 词表 id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self._width = EXPANDED_WIDTH
        self.setFixedWidth(self._width)
        self._buttons: dict[str, NavItemButton] = {}
        self._groups: list[tuple[str, list[WordList]]] = []
        self._keywords = ""  # 当前过滤词
        self._selected_id: Optional[str] = None

        self._ani = QPropertyAnimation(self, b"drawerWidth", self)
        self._ani.setDuration(220)
        self._ani.setEasingCurve(QEasingCurve.Type.OutCubic)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # 顶部：折叠按钮 + 标题
        top = QFrame(self)
        top.setFixedHeight(36)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(4, 0, 4, 0)
        top_layout.setSpacing(8)
        self._toggle_btn = ToolButton(FluentIcon.MENU, top)
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setIconSize(QSize(16, 16))
        self._toggle_btn.clicked.connect(self.toggle)
        top_layout.addWidget(self._toggle_btn)
        self._title = QLabel("词表导航", top)
        self._title.setStyleSheet("font-weight: bold; font-size: 14px;")
        top_layout.addWidget(self._title)
        top_layout.addStretch(1)
        outer.addWidget(top)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        # 滚动区承载分组内容
        from qfluentwidgets import ScrollArea
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.enableTransparentBackground()
        self._content = QWidget(self.scroll)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(2)
        self._content_layout.addStretch(1)
        self.scroll.setWidget(self._content)
        outer.addWidget(self.scroll, 1)

        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(self._on_theme)
        self._refresh_toggle_icon()

    # ----------------------------------------------------------- 宽度动画属性
    def get_drawer_width(self) -> int:
        return self._width

    def set_drawer_width(self, w: int) -> None:
        self._width = int(w)
        self.setFixedWidth(self._width)

    drawerWidth = Property(int, get_drawer_width, set_drawer_width)

    # ----------------------------------------------------------- 主题
    def _on_theme(self) -> None:
        self._title.setStyleSheet(
            f"color: {'#FFFFFF' if isDarkTheme() else '#1A1A1A'}; font-weight: bold; font-size: 14px;")
        self._refresh_toggle_icon()
        for btn in self._buttons.values():
            btn.refresh_theme()

    def _refresh_toggle_icon(self) -> None:
        icon = FluentIcon.MENU if self._collapsed else FluentIcon.LEFT_ARROW
        self._toggle_btn.setIcon(icon)

    # ----------------------------------------------------------- 数据
    def set_wordlists(self, groups: list[tuple[str, list[WordList]]]) -> None:
        """重建分组（groups: [(分组标题, [WordList]), ...]）。"""
        self._groups = groups
        # 清空旧按钮（保留末尾 stretch）
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._buttons.clear()

        for header, wls in groups:
            header_label = self._make_header(header)
            self._content_layout.insertWidget(self._content_layout.count() - 1, header_label)
            for wl in wls:
                btn = NavItemButton(wl, self._content)
                btn.clicked.connect(lambda _id=wl.id: self.select(_id))  # type: ignore[misc]
                btn.set_collapsed(self._collapsed)
                self._content_layout.insertWidget(self._content_layout.count() - 1, btn)
                self._buttons[wl.id] = btn

        self._apply_filter()
        if self._selected_id in self._buttons:
            self._buttons[self._selected_id].set_active(True)

    def _make_header(self, text: str) -> QLabel:
        label = QLabel(text, self._content)
        label.setObjectName("navHeader")
        label.setFixedHeight(26)
        label.setStyleSheet(
            f"color: {'#8A8A8A' if not isDarkTheme() else '#9A9A9A'};"
            "font-size: 11px; font-weight: bold; padding-left: 6px;")
        label.setProperty("_nav_header", True)
        return label

    # ----------------------------------------------------------- 过滤
    def filter(self, kw: str) -> None:
        self._keywords = kw.strip().lower()
        self._apply_filter()

    def _apply_filter(self) -> None:
        kw = self._keywords
        # 记录每个分组可见按钮数，决定分组标题是否显示
        visible_per_group: list[int] = []
        idx = 0
        for _header, wls in self._groups:
            cnt = 0
            for wl in wls:
                btn = self._buttons.get(wl.id)
                if btn is None:
                    continue
                show = (not kw) or (kw in wl.name.lower())
                btn.setVisible(show)
                cnt += int(show)
            visible_per_group.append(cnt)
            idx += 1
        # 分组标题显隐
        header_widgets = [w for w in (self._content_layout.itemAt(i).widget()
                           for i in range(self._content_layout.count() - 1))
                           if w is not None and w.property("_nav_header")]
        for label, cnt in zip(header_widgets, visible_per_group):
            label.setVisible(cnt > 0 and not self._collapsed)

    # ----------------------------------------------------------- 选择 / 折叠
    def select(self, wid: str) -> None:
        if self._selected_id in self._buttons:
            self._buttons[self._selected_id].set_active(False)
        self._selected_id = wid
        if wid in self._buttons:
            self._buttons[wid].set_active(True)
        self.selected.emit(wid)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._refresh_toggle_icon()
        # 文本显隐：先切换子控件状态，再动画宽度
        for btn in self._buttons.values():
            btn.set_collapsed(collapsed)
        self._title.setVisible(not collapsed)
        self._apply_filter()  # 重新计算分组标题显隐
        target = COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH
        if animate:
            self._ani.stop()
            self._ani.setStartValue(self._width)
            self._ani.setEndValue(target)
            self._ani.start()
        else:
            self.set_drawer_width(target)

    def selected_id(self) -> Optional[str]:
        return self._selected_id

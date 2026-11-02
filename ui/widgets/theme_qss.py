"""原生 Qt 列表/表格控件的 Fluent 主题样式。

qfluentwidgets 只给自己的 ``TableWidget`` / ``ListView`` 内置了样式表；项目里仍有一
些**原生** ``QTableWidget`` / ``QListWidget``（词表编辑器的 ``ItemTable``、导入预览表、
词表页的两个列表）。在深色主题下它们没有背景会回退成黑底，且选中行无高亮。

这里用 ``isDarkTheme()`` + ``qconfig.themeChanged`` 给它们套一份「明暗双主题、主题切换时
自动重渲染」的样式表，确保背景永远是主题色（绝不为黑）、文字可读、选中可见。
（直接读写 ``setStyleSheet``，不依赖 ``setCustomStyleSheet`` 的 compose 机制，行为可预测。）
"""

from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QTableWidget, QTreeWidget
from qfluentwidgets import isDarkTheme, qconfig

# --- 表格（原生 QTableWidget / ItemTable） -----------------------------------
_TABLE_LIGHT = """
QTableWidget {
    background-color: #ffffff;
    border: 1px solid rgba(0, 0, 0, 15);
    border-radius: 6px;
    gridline-color: rgba(0, 0, 0, 15);
    color: #1f1f1f;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QHeaderView::section {
    background-color: rgb(243, 243, 243);
    color: #333333;
    border: none;
    border-bottom: 1px solid rgba(0, 0, 0, 15);
    padding: 6px 8px;
    font: 13px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QTableWidget::item {
    padding: 4px 6px;
}
QTableWidget::item:selected {
    background-color: rgb(204, 232, 255);
    color: #1f1f1f;
}
QTableWidget::item:focus {
    border: none;
}
"""

_TABLE_DARK = """
QTableWidget {
    background-color: #2b2b2b;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 6px;
    gridline-color: rgba(255, 255, 255, 15);
    color: #ffffff;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QHeaderView::section {
    background-color: #333333;
    color: #dddddd;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 15);
    padding: 6px 8px;
    font: 13px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QTableWidget::item {
    padding: 4px 6px;
}
QTableWidget::item:selected {
    background-color: #2b5a8c;
    color: #ffffff;
}
QTableWidget::item:focus {
    border: none;
}
"""

# --- 列表（原生 QListWidget） -----------------------------------------------
_LIST_LIGHT = """
QListWidget {
    background-color: #ffffff;
    border: 1px solid rgba(0, 0, 0, 15);
    border-radius: 6px;
    outline: none;
    color: #1f1f1f;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: rgb(204, 232, 255);
    color: #1f1f1f;
}
QListWidget::item:hover {
    background-color: rgba(0, 0, 0, 6);
}
"""

_LIST_DARK = """
QListWidget {
    background-color: #2b2b2b;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 6px;
    outline: none;
    color: #ffffff;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: #2b5a8c;
    color: #ffffff;
}
QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 10);
}
"""


def _disconnect(signal, slot) -> None:
    """安全断连（槽可能已失效）。"""
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def _apply(widget, light: str, dark: str) -> None:
    """按当前主题把样式表写进控件（控件已销毁时静默跳过）。"""
    try:
        widget.setStyleSheet(dark if isDarkTheme() else light)
    except RuntimeError:
        pass


def style_table(widget: QTableWidget) -> None:
    """给原生 QTableWidget 套主题感知样式（非黑底、含选中高亮）。"""
    def handler(_=None) -> None:
        _apply(widget, _TABLE_LIGHT, _TABLE_DARK)

    handler()  # 立即应用当前主题
    qconfig.themeChanged.connect(handler)  # 主题切换时自动重渲染
    # 控件销毁后断开连接，避免悬空回调与引用泄漏
    widget.destroyed.connect(lambda *_: _disconnect(qconfig.themeChanged, handler))


def style_list(widget: QListWidget) -> None:
    """给原生 QListWidget 套主题感知样式（非黑底、含选中高亮）。"""
    def handler(_=None) -> None:
        _apply(widget, _LIST_LIGHT, _LIST_DARK)

    handler()
    qconfig.themeChanged.connect(handler)
    widget.destroyed.connect(lambda *_: _disconnect(qconfig.themeChanged, handler))


# --- 树（原生 QTreeWidget：词表页分类导航树） -------------------------------
_TREE_LIGHT = """
QTreeWidget {
    background-color: #ffffff;
    border: 1px solid rgba(0, 0, 0, 15);
    border-radius: 6px;
    outline: none;
    color: #1f1f1f;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QTreeWidget::item {
    padding: 6px 8px;
    border-radius: 4px;
}
QTreeWidget::item:selected {
    background-color: rgb(204, 232, 255);
    color: #1f1f1f;
}
QTreeWidget::item:hover {
    background-color: rgba(0, 0, 0, 6);
}
QTreeWidget::branch {
    background: transparent;
}
"""

_TREE_DARK = """
QTreeWidget {
    background-color: #2b2b2b;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 6px;
    outline: none;
    color: #ffffff;
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
}
QTreeWidget::item {
    padding: 6px 8px;
    border-radius: 4px;
}
QTreeWidget::item:selected {
    background-color: #2b5a8c;
    color: #ffffff;
}
QTreeWidget::item:hover {
    background-color: rgba(255, 255, 255, 10);
}
QTreeWidget::branch {
    background: transparent;
}
"""


def style_tree(widget: QTreeWidget) -> None:
    """给原生 QTreeWidget 套主题感知样式（非黑底、含选中高亮）。"""
    def handler(_=None) -> None:
        _apply(widget, _TREE_LIGHT, _TREE_DARK)

    handler()
    qconfig.themeChanged.connect(handler)
    widget.destroyed.connect(lambda *_: _disconnect(qconfig.themeChanged, handler))


# --- 页面根容器：主题背景（杜绝原生控件/滚动区透出黑底） ----------------------
# 浅色用 Fluent 浅灰底，深色用 Fluent 深色底；主题切换时自动重渲染。
_PAGE_LIGHT = "background-color: #f5f5f5;"
_PAGE_DARK = "background-color: #1e1e1e;"


def style_page(widget: QWidget) -> None:
    """给页面根容器套主题感知背景，避免子控件透明时透出黑底。"""
    def handler(_=None) -> None:
        _apply(widget, _PAGE_LIGHT, _PAGE_DARK)

    handler()
    qconfig.themeChanged.connect(handler)
    widget.destroyed.connect(lambda *_: _disconnect(qconfig.themeChanged, handler))


# --- 普通文本控件：主题感知文字颜色 ----------------------------------------
# qfluentwidgets 的全局样式表在浅色主题下可能把部分原生 QLabel 的文字渲染成白色，
# 这里显式按当前主题设置 color，确保浅底黑字、深底白字。
_LABEL_LIGHT = "color: #1A1A1A;"
_LABEL_DARK = "color: #FFFFFF;"


def style_label(widget: QWidget) -> None:
    """给 QLabel/文本控件套主题感知文字颜色，避免浅色主题下出现白字。"""
    def handler(_=None) -> None:
        _apply(widget, _LABEL_LIGHT, _LABEL_DARK)

    handler()
    qconfig.themeChanged.connect(handler)
    widget.destroyed.connect(lambda *_: _disconnect(qconfig.themeChanged, handler))

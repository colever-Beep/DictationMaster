"""对话框基类与通用提示辅助函数。

对应规范 §3.4：所有对话框统一继承自自建的 ``FluentContentDialog`` 基类，
由 ``MaskDialogBase``（qfluentwidgets）提供遮罩与 ``exec()``（返回 DialogCode，
语义与 ``QDialog`` 一致：``Accepted`` 为真）。基类提供标题栏（36px）、内容区
``viewLayout`` 与底部按钮行 ``button_row``，子类只往里塞控件即可。

另提供 ``msg_info`` / ``msg_confirm`` 等辅助函数，统一把默认按钮汉化并兜底 parent
（规格 §8.1#6：``MessageBox`` 的 parent 不能为 None，否则读 ``parent.width()`` 崩溃）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    FluentStyleSheet,
    MaskDialogBase,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
)

# 标题栏高度（规范 §3.4 要求留出 36px）
_TITLE_BAR_H = 36

# 无 parent 时的兜底窗口引用（必须持有引用，否则会被 GC 回收导致崩溃）
_fallback_parents: list[QWidget] = []


def _ensure_parent(parent: QWidget | None) -> QWidget:
    """保证返回一个非 None 的 parent 窗口。

    ``MaskDialogBase.__init__`` 会读取 ``parent.width()`` / ``parent.height()``，
    parent 为 None 必然崩溃（规格 §8.1#6）。此处的兜底顺序：

    1. 调用方传入的 parent；
    2. 当前活动窗口（``QApplication.activeWindow()``）；
    3. 一个隐藏的离屏 QWidget（offscreen 测试、程序启动早期等无活动窗口的场景）。

    第 3 步的窗口会被加入模块级列表以防被 Python GC 回收。
    """
    if parent is not None:
        return parent
    active = QApplication.activeWindow()
    if active is not None:
        return active
    holder = QWidget()
    holder.setFixedSize(1024, 768)
    holder.hide()
    _fallback_parents.append(holder)
    return holder


class FluentContentDialog(MaskDialogBase):
    """内容对话框基类：标题栏 + 内容区 + 底部按钮行。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        # MaskDialogBase 在 __init__ 中读取 parent.width()/height()，parent 不能为 None；
        # 缺失时依次回退活动窗口 / 隐藏离屏窗口（规格 §8.1#6）
        parent = _ensure_parent(parent)
        super().__init__(parent)
        self.setMinimumWidth(520)

        # 真正的根布局（MaskDialogBase 的 self.widget 是中心 QFrame）
        from PySide6.QtWidgets import QVBoxLayout
        vbox = QVBoxLayout(self.widget)
        vbox.setContentsMargins(24, 44, 24, 20)
        vbox.setSpacing(12)

        # 标题栏：标题 + 关闭按钮
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.title_label = TitleLabel(title, self.widget)
        bar.addWidget(self.title_label)
        bar.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        close_btn = TransparentToolButton(FluentIcon.CLOSE, self.widget)
        close_btn.setFixedHeight(_TITLE_BAR_H)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        vbox.addLayout(bar)

        # 内容区
        self.viewLayout = QVBoxLayout()
        self.viewLayout.setSpacing(12)
        vbox.addLayout(self.viewLayout)

        vbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # 底部按钮行（右侧对齐，左侧留弹性空间）
        self.button_row = QHBoxLayout()
        self.button_row.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        vbox.addLayout(self.button_row)

        # 套用 Fluent 对话框样式表：MaskDialogBase 只给窗口设了透明背景，
        # 不给中心内容（#centerWidget）任何背景 → 子窗口内容区透明、能看到背后遮罩。
        # 官方 Dialog 的修法就是 apply(FluentStyleSheet.DIALOG)，其 qss 给
        # #centerWidget 设定了主题背景色与边框，并随主题自动切换。
        FluentStyleSheet.DIALOG.apply(self)

    def add_button(self, btn: QWidget) -> None:
        """向底部按钮行追加一个按钮（右侧）。"""
        self.button_row.addWidget(btn)

    # ------------------------------------------------------------------ 线程收尾
    def shutdown_workers(self) -> None:
        """等待本对话框启动的后台线程结束。

        ``MaskDialogBase`` 覆盖了 ``QDialog.done()``，关闭对话框不会触发
        ``closeEvent``，因此统一在 ``done()`` 里收尾，避免
        ``QThread: Destroyed while thread is still running`` 崩溃。
        """
        for w in list(getattr(self, "_gh_workers", []) or []):
            try:
                w.shutdown()
            except Exception:  # noqa: BLE001  收尾失败不应阻断关闭
                pass
        self._gh_workers = []

    def done(self, code: int) -> None:  # noqa: D401
        self.shutdown_workers()
        super().done(code)


def _safe_parent(parent: QWidget | None) -> QWidget:
    """MessageBox 的 parent 不能为 None，缺失时用活动窗口 / 隐藏离屏窗口兜底。"""
    return _ensure_parent(parent)


def msg_info(parent: QWidget | None, title: str, content: str) -> None:
    """信息提示框（仅「确定」）。"""
    box = MessageBox(title, content, _safe_parent(parent))
    box.cancelButton.hide()
    box.yesButton.setText("确定")
    box.exec()


def msg_confirm(parent: QWidget | None, title: str, content: str,
                yes: str = "确定", no: str = "取消") -> bool:
    """确认框：返回用户是否点了「确定」。"""
    box = MessageBox(title, content, _safe_parent(parent))
    box.yesButton.setText(yes)
    box.cancelButton.setText(no)
    return bool(box.exec())


class TextInputDialog(FluentContentDialog):
    """单行文本输入对话框（用于重命名等场景）。"""

    def __init__(self, title: str, label: str = "", text: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        if label:
            self.viewLayout.addWidget(SubtitleLabel(label, self.widget))
        self.line = QLineEdit(self.widget)
        self.line.setText(text)
        self.line.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.line)

        cancel = PushButton("取消", self.widget)
        cancel.clicked.connect(self.reject)
        ok = PrimaryPushButton("确定", self.widget)
        ok.clicked.connect(self.accept)
        self.add_button(cancel)
        self.add_button(ok)
        self.line.returnPressed.connect(self.accept)

    def text_value(self) -> str:
        """返回去除首尾空白的输入文本。"""
        return self.line.text().strip()

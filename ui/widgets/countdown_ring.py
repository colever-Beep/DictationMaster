"""环形倒计时自绘控件（规范 §4.1 / §F3）。

用于书写倒计时（以及倒计时阶段）的环形进度展示。纯 ``QWidget`` 自绘，
不依赖任何第三方绘图库；主题为跟随 Fluent 蓝的描边色。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class CountdownRing(QWidget):
    """环形倒计时：``set_value(remaining, total)`` 后重绘，中心显示剩余秒数。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._remaining = 0.0
        self._total = 0.0
        self.setFixedSize(140, 140)

    def set_value(self, remaining: float, total: float) -> None:
        """设置剩余/总时长（秒）。``total<=0`` 时画空环。"""
        self._remaining = max(0.0, remaining)
        self._total = max(0.0, total)
        self.update()

    def clear(self) -> None:
        """清空显示为空白环。"""
        self._remaining = 0.0
        self._total = 0.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        margin = 12
        radius = min(w, h) / 2 - margin

        # 底环（浅灰）
        bg = QColor("#D5D9E0") if self._is_dark() else QColor("#E3E6EB")
        pen = QPen(bg, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(int(cx - radius), int(cy - radius),
                           int(radius * 2), int(radius * 2))

        # 进度弧（剩余比例）：从 12 点方向顺时针
        if self._total > 0:
            frac = self._remaining / self._total
            accent = QColor("#0F6CBD")
            pen = QPen(accent, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            span = int(360 * frac)
            # QPainter 角度：0 度在 3 点方向，顺时针为正；12 点即 -90 度
            painter.drawArc(int(cx - radius), int(cy - radius),
                            int(radius * 2), int(radius * 2),
                            -90 * 16, -span * 16)

        # 中心文字：剩余秒数（向上取整）
        if self._total > 0:
            text = str(int(self._remaining + 0.999) if self._remaining > 0 else 0)
            fg = QColor("#FFFFFF") if self._is_dark() else QColor("#1A1A1A")
            painter.setPen(fg)
            font = painter.font()
            font.setPointSize(32)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _is_dark() -> bool:
        """粗略判断当前是否为深色主题（用于描边底色）。"""
        try:
            from qfluentwidgets import qconfig, Theme
            return qconfig.theme == Theme.DARK
        except Exception:  # noqa: BLE001
            return False

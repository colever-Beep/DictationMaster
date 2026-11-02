"""生成应用图标 assets/app.ico（多尺寸，纯 Qt 绘制，无需额外依赖）。

图标设计：Fluent 蓝圆角方块 + 白色「听」字 + 右下角小喇叭点缀。
运行：python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]

ACCENT = QColor("#0F6CBD")
ACCENT_DARK = QColor("#0B5394")


def _draw(size: int) -> QImage:
    """按给定边长绘制一张图标位图（喇叭 + 声波，不依赖系统字体）。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 圆角方块底（竖向渐变）
    from PySide6.QtGui import QLinearGradient

    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, ACCENT)
    grad.setColorAt(1.0, ACCENT_DARK)
    path = QPainterPath()
    radius = size * 0.22
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.fillPath(path, QBrush(grad))

    # 喇叭主体：矩形振膜 + 梯形声锥（白色）
    white = QColor(255, 255, 255, 245)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(white))
    u = size / 256.0  # 设计基准 256，按比例缩放
    cone = QPainterPath()
    cone.moveTo(56 * u, 104 * u)
    cone.lineTo(96 * u, 104 * u)
    cone.lineTo(136 * u, 68 * u)
    cone.lineTo(136 * u, 188 * u)
    cone.lineTo(96 * u, 152 * u)
    cone.lineTo(56 * u, 152 * u)
    cone.closeSubpath()
    p.drawPath(cone)

    # 两道声波弧线
    from PySide6.QtGui import QPen

    pen = QPen(white)
    pen.setWidthF(14 * u)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    # 第一道弧
    rect1 = QRectF(140 * u, 88 * u, 58 * u, 80 * u)
    p.drawArc(rect1, -55 * 16, 110 * 16)
    # 第二道弧
    pen.setWidthF(12 * u)
    p.setPen(pen)
    rect2 = QRectF(158 * u, 64 * u, 74 * u, 128 * u)
    p.drawArc(rect2, -50 * 16, 100 * 16)

    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841  QPainter 文本渲染需要 Qt 应用
    images = [(s, _png_bytes(_draw(s))) for s in SIZES]

    # 手工拼装 ICO：6 字节头 + 每图 16 字节目录项 + PNG 数据（Vista+ 支持 PNG 负载）
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blob = b""
    for size, data in images:
        entry_size = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", entry_size, entry_size, 0, 0, 1, 32,
                               len(data), offset)
        blob += data
        offset += len(data)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + blob)
    print(f"图标已生成：{OUT}（{OUT.stat().st_size / 1024:.1f} KB，{count} 个尺寸）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

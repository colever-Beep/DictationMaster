"""关于页（M1 展示版本信息，M6 补充检查更新等占位）。"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, SubtitleLabel

from ui.pages.base import PageBase


class AboutPage(PageBase):
    """关于页：展示依赖版本与应用信息。"""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__("关于", parent)

        try:
            from PySide6 import __version__ as pyside_ver
        except Exception:  # noqa: BLE001
            pyside_ver = "unknown"
        try:
            import edge_tts
            edge_ver = edge_tts.__version__
        except Exception:  # noqa: BLE001
            edge_ver = "unknown"
        try:
            import qfluentwidgets
            qf_ver = qfluentwidgets.__version__
        except Exception:  # noqa: BLE001
            qf_ver = "unknown"

        card = CardWidget(self)
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(8)

        vbox.addWidget(SubtitleLabel("听写助手 Dictation Master"))
        vbox.addWidget(BodyLabel("对标希沃白板听写的本地独立听写软件（M1 骨架）。"))
        vbox.addWidget(BodyLabel(f"PySide6: {pyside_ver}"))
        vbox.addWidget(BodyLabel(f"qfluentwidgets: {qf_ver}"))
        vbox.addWidget(BodyLabel(f"edge-tts: {edge_ver}"))

        self.add_widget(card)

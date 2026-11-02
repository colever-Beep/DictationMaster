"""关于界面。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from qfluentwidgets import SubtitleLabel, BodyLabel, CaptionLabel, FluentIcon


class AboutInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(14)
        root.setAlignment(Qt.AlignTop)

        root.addWidget(SubtitleLabel("Edge-TTS 听写"))
        root.addWidget(BodyLabel(
            "一款仿照希沃白板「听写」功能、基于 Edge-TTS 引擎的听写软件。"
        ))

        feats = BodyLabel(
            "功能特性：\n"
            "· 词库每行一词，可导入/导出 txt\n"
            "· 中文多种发音人（需联网获取在线列表）\n"
            "· 语速 -50%~+50%，音调 ±20Hz\n"
            "· 朗读遍数 1~5 遍，词间/重复间隔可调\n"
            "· 暂停 / 继续 / 停止 / 上词 / 下词 控制\n"
            "· 停顿倒计时提示，进度可视化"
        )
        feats.setWordWrap(True)
        root.addWidget(feats)

        tip = CaptionLabel(
            "提示：Edge-TTS 需要联网调用微软语音服务；首次使用建议在「设置」中刷新发音人列表。"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        link = CaptionLabel("技术栈：PySide6 + Edge-TTS + qfluentwidgets（Fluent 风格）")
        link.setWordWrap(True)
        root.addWidget(link)

        root.addStretch(1)

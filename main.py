"""听写助手入口。

负责：高 DPI、单实例、全局异常钩子、主题恢复、启动主窗口。
运行方式（在 tingxie 目录下）：python main.py
"""

from __future__ import annotations

import os
import pathlib
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# 将脚本所在目录加入 sys.path，保证以任意 cwd 启动时绝对导入可用
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app_config import cfg, init_config, apply_theme  # noqa: E402
from core.logger import install_excepthooks, get_logger  # noqa: E402
from core.paths import APP_NAME  # noqa: E402
from core.services import Services  # noqa: E402
from qfluentwidgets import qconfig  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

LOG = get_logger()
_INSTANCE_NAME = f"{APP_NAME}-Instance"


def _resource_path(rel: str) -> pathlib.Path:
    """资源文件绝对路径：兼容开发运行与 PyInstaller 冻结运行。"""
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    return base / rel


def _app_icon() -> QIcon | None:
    """应用图标（assets/app.ico），缺失时返回 None 不影响启动。"""
    icon_file = _resource_path("assets/app.ico")
    if icon_file.exists():
        return QIcon(str(icon_file))
    return None


def _single_instance() -> tuple[bool, QLocalServer | None]:
    """确保单实例运行。返回 (是否为主实例, 主实例的 LocalServer)。"""
    server = QLocalServer()
    server.removeServer(_INSTANCE_NAME)  # 清理上次残留的 socket
    if server.listen(_INSTANCE_NAME):
        return True, server

    # 已有实例在运行：发送激活信号后退出
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_NAME)
    if sock.waitForConnected(1000):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.close()
    return False, None


def _on_theme_changed(_value) -> None:
    """主题变更：立即应用并落盘持久化。"""
    apply_theme()
    qconfig.save()


def _probe_tts_online(services, window) -> None:
    """启动时轻量合成一个「测」字探测 edge-tts 可用性（规范 §F6）。

    成功：静默（不打扰用户）；失败：InfoBar 提示一次并说明会走离线引擎。
    探测是异步的，不阻塞启动。
    """
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import InfoBar, InfoBarPosition

    state = {"done": False}

    def ok(_rid, _path):
        if _rid != "__startup_probe__":
            return
        state["done"] = True
        LOG.info("edge-tts 联网探测成功。")

    def fail(_rid, err):
        if _rid != "__startup_probe__" or state["done"]:
            return
        state["done"] = True
        LOG.warning("edge-tts 联网探测失败：%s", err)
        detail = str(err)
        if "No audio was received" in detail:
            detail = ("edge-tts 已连接但服务器未返回音频。通常是网络无法直连微软 TTS "
                      "或代理异常：请在「设置 → 语音 → 网络代理」填写可用代理后重试；"
                      "也可点「语音连通性测试」查看真实错误。")
        InfoBar.warning(
            "离线模式",
            f"无法连接 edge-tts（{detail}）\n本次听写将使用系统离线语音引擎。"
            "联网并配置好代理后重启即可恢复自然音色。",
            duration=8000, position=InfoBarPosition.TOP_RIGHT, parent=window,
        )

    services.tts.single_ready.connect(ok)
    services.tts.single_failed.connect(fail)
    QApplication.processEvents()
    services.tts.synthesize("__startup_probe__", "测", "zh-CN-XiaoxiaoNeural",
                            "-10%", "+0%", "+0Hz")


def _run_first_guide(window, cfg, services) -> None:
    """首次启动引导（规范 §F6，3 步）。完成后落配置并可选创建词表。"""
    from qfluentwidgets import InfoBar, InfoBarPosition, qconfig

    from ui.dialogs.first_run import FirstRunDialog

    data = FirstRunDialog.ask(window)
    cfg.first_run_done.value = True   # 无论完成还是跳过，都不再重复打扰
    qconfig.save()
    if not data:
        return
    cfg.subject.value = data["subject"]
    qconfig.save()

    name = data["wordlist_name"]
    words = data["words"]
    if not words:
        return
    from data.models import WordItem, WordList
    from data.repository import gen_id, save_wordlist

    wl = WordList(
        id=gen_id("wl"),
        name=name or "我的第一份词表",
        subject=data["subject"],
        items=[WordItem(id=gen_id("it"), text=w, lang="zh"
                        if data["subject"] == "chinese" else "en") for w in words],
    )
    save_wordlist(wl)
    InfoBar.success("词表已创建", f"「{wl.name}」共 {len(wl.items)} 词，去听写页试试吧！",
                    duration=5000, position=InfoBarPosition.TOP_RIGHT, parent=window)


def main() -> int:
    # Qt6 推荐的高 DPI 处理方式
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    install_excepthooks()

    is_primary, server = _single_instance()
    if not is_primary:
        LOG.info("已有实例在运行，本次启动退出。")
        return 0

    init_config()
    apply_theme()
    cfg.theme.valueChanged.connect(_on_theme_changed)

    # 首次运行把内置示例教材词库 + 随包内置词表复制到用户目录（可插拔，不覆盖用户自建）
    from data.repository import seed_textbooks, seed_wordlists
    seed_textbooks()
    seed_wordlists()

    # 历史记录 / 错题本数据库（幂等建表）
    import data.database as db
    db.init_db()

    # 语音层服务：聚合 TTS / 播放器 / 离线降级 / 音色管理
    services = Services()
    services.apply_config(cfg)
    services.refresh_voices()

    window = MainWindow(services)
    if server is not None:
        # 收到其他实例的激活信号时，把已存在的窗口提到前台
        server.newConnection.connect(
            lambda: (window.showNormal(), window.activateWindow())
        )
    # 应用退出时清理后台 loop 线程与播放器
    app.aboutToQuit.connect(services.shutdown)
    window.show()

    # 首启引导（仅第一次）与联网探测（§F6）
    if not cfg.first_run_done.value:
        _run_first_guide(window, cfg, services)
        window.dictation_page.refresh_wordlists()
    if cfg.check_network_on_start.value:
        _probe_tts_online(services, window)

    LOG.info("听写助手已启动。")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

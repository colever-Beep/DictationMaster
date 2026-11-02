"""Edge-TTS 听写 —— 主入口（PySide6 + qfluentwidgets）。"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication

from ui.fluent import AppWindow, set_app_theme
from core.config import Config
from ui.home import HomeInterface
from ui.settings import SettingsInterface
from ui.about import AboutInterface
from qfluentwidgets import FluentIcon, NavigationItemPosition


def main():
    QCoreApplication.setApplicationName("EdgeTTS-Dictation")
    QCoreApplication.setOrganizationName("TingxieApp")

    app = QApplication(sys.argv)

    config = Config()
    set_app_theme(config.theme == "dark")

    window = AppWindow()

    home = HomeInterface(config)
    settings = SettingsInterface(config)
    about = AboutInterface()
    window.add_page(home, FluentIcon.HOME, "听写", "home")
    window.add_page(settings, FluentIcon.SETTING, "设置", "settings", NavigationItemPosition.BOTTOM)
    window.add_page(about, FluentIcon.INFO, "关于", "about", NavigationItemPosition.BOTTOM)

    settings.config_applied.connect(home.apply_settings)

    def apply_theme(dark):
        config.theme = "dark" if dark else "light"
        set_app_theme(dark)
        settings.theme_switch.blockSignals(True)
        settings.theme_switch.setChecked(dark)
        settings.theme_switch.blockSignals(False)

    window.on_theme_changed(apply_theme)
    settings.theme_toggled.connect(apply_theme)

    def _cleanup():
        try:
            home._cleanup_tmp()
            if home.player is not None:
                home.player.cleanup()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

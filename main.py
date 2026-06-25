# main.py - Entry point, manages screen navigation via QStackedWidget

import sys
import os

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QSystemTrayIcon, QMenu
from PySide6.QtGui import QFontDatabase, QIcon, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt

from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.login_screen import LoginScreen
from ui.screens.pipeline_screen import PipelineScreen
from ui.styles.theme import GLOBAL_QSS, CYAN

SCREEN_WELCOME = 0
SCREEN_LOGIN   = 1


def _make_tray_icon() -> QIcon:
    """Create a small amber square as the system tray icon (no file dependency)."""
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(CYAN))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(1, 1, 14, 14, 3, 3)
    p.end()
    return QIcon(px)


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Photo2Solid")
        self.resize(1600, 900)
        self.setMinimumSize(1100, 700)

        self.run_mode    = None
        self.credentials = None
        self.user_info   = {}
        self._docker_check_active = False   # re-entry guard for blocking Docker check

        # Persistent pipeline screens - keep alive when user goes home
        self._pipeline_screens: dict[str, PipelineScreen] = {}

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.welcome = WelcomeScreen()
        self.login   = LoginScreen()

        self.stack.addWidget(self.welcome)  # index 0
        self.stack.addWidget(self.login)    # index 1

        self.welcome.local_selected.connect(self._on_local)
        self.welcome.remote_selected.connect(self._on_remote)
        self.login.back_requested.connect(self._go_home)
        self.login.login_success.connect(self._on_login_success)

        self.stack.setCurrentIndex(SCREEN_WELCOME)

        # System tray for job notifications
        self._setup_tray()

    # -- Tray ------------------------------------------------------------------

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon())
        self._tray.setToolTip("Photo2Solid")

        tray_menu = QMenu()
        act_show = tray_menu.addAction("Show Photo2Solid")
        act_show.triggered.connect(self._bring_to_front)
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction("Quit")
        act_quit.triggered.connect(QApplication.quit)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(
            lambda reason: self._bring_to_front()
            if reason == QSystemTrayIcon.DoubleClick else None
        )
        self._tray.show()

    def notify(self, title: str, message: str):
        """Show a system tray balloon notification."""
        if QSystemTrayIcon.isSystemTrayAvailable() and self._tray.isVisible():
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    def _bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # -- Navigation -------------------------------------------------------------

    def _go_home(self):
        self.stack.setCurrentWidget(self.welcome)

    def _on_remote(self):
        self.run_mode = "remote"
        self.stack.setCurrentWidget(self.login)

    def _on_local(self):
        # Prevent re-entry while check_docker_running() is blocking the event loop
        if self._docker_check_active:
            return
        self._docker_check_active = True

        from PySide6.QtCore import QSettings
        from ui.components.DockerWarningDialog import (
            DockerWarningDialog, DockerStartDialog, check_docker_running, find_docker_desktop,
        )

        try:
            docker_ok = check_docker_running()
        finally:
            self._docker_check_active = False

        if not docker_ok:
            # Determine whether Docker is missing entirely or just not started
            docker_path = find_docker_desktop()
            dlg = DockerStartDialog(docker_missing=(docker_path is None), parent=self)
            if dlg.exec() != DockerStartDialog.Accepted:
                return
            # User waited for Docker to start - verify once more
            if not check_docker_running():
                return

        # 2. Show one-time prerequisites checklist (has "don't show again")
        settings = QSettings("Photo2Solid", "App")
        if not DockerWarningDialog.run_if_needed(settings, self):
            return

        self.run_mode  = "local"
        self.user_info = {}
        self._launch_pipeline()

    def _on_login_success(self, manager):
        self.credentials = manager
        try:
            self.user_info = manager.get_user_info()
            print(f"[App] Logged in as: {self.user_info.get('name')} ({self.user_info.get('email')})")
        except Exception as e:
            print(f"[App] Could not fetch user info: {e}")
            self.user_info = {}
        self._launch_pipeline()

    # -- Sign-out ---------------------------------------------------------------

    def _on_signed_out(self, mode: str):
        """Discard the pipeline screen and credentials so next login starts fresh."""
        if mode in self._pipeline_screens:
            widget = self._pipeline_screens.pop(mode)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.credentials = None
        self.user_info   = {}
        self._go_home()

    # -- Pipeline screen management ---------------------------------------------

    def _launch_pipeline(self):
        mode = self.run_mode

        if mode in self._pipeline_screens:
            # Reuse existing screen - preserves in-flight jobs
            self.stack.setCurrentWidget(self._pipeline_screens[mode])
            return

        pipeline = PipelineScreen(
            run_mode=mode,
            credentials=self.credentials,
            user_info=self.user_info,
        )
        pipeline.home_requested.connect(self._go_home)
        pipeline.notification.connect(self.notify)
        pipeline.signed_out.connect(lambda: self._on_signed_out("remote"))

        self._pipeline_screens[mode] = pipeline
        self.stack.addWidget(pipeline)
        self.stack.setCurrentWidget(pipeline)


def _load_fonts():
    fonts_dir = os.path.join(os.path.dirname(__file__), "ui", "assets", "fonts")
    if os.path.isdir(fonts_dir):
        for root, _, files in os.walk(fonts_dir):
            for f in files:
                if f.endswith((".ttf", ".otf")):
                    QFontDatabase.addApplicationFont(os.path.join(root, f))


if __name__ == "__main__":
    os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(GLOBAL_QSS)
    # Keep app alive when all windows are minimised to tray
    app.setQuitOnLastWindowClosed(False)

    _load_fonts()

    win = AppWindow()
    win.showMaximized()
    sys.exit(app.exec())

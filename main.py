# main.py — Entry point, manages screen navigation via QStackedWidget

import sys
import os

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtGui import QFontDatabase

from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.login_screen import LoginScreen
from ui.screens.pipeline_screen import PipelineScreen
from ui.styles.theme import GLOBAL_QSS

SCREEN_WELCOME  = 0
SCREEN_LOGIN    = 1
SCREEN_PIPELINE = 2


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Neural Forge — AI 3D Pipeline")
        self.resize(1600, 900)
        self.setMinimumSize(1100, 700)

        self.run_mode    = None
        self.credentials = None
        self.user_info   = {}

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.welcome = WelcomeScreen()
        self.login   = LoginScreen()

        self.stack.addWidget(self.welcome)  # 0
        self.stack.addWidget(self.login)    # 1

        self.welcome.local_selected.connect(self._on_local)
        self.welcome.remote_selected.connect(self._on_remote)
        self.login.back_requested.connect(lambda: self.stack.setCurrentIndex(SCREEN_WELCOME))
        self.login.login_success.connect(self._on_login_success)

        self.stack.setCurrentIndex(SCREEN_WELCOME)

    def _on_local(self):
        self.run_mode  = "local"
        self.user_info = {}
        self._launch_pipeline()

    def _on_remote(self):
        self.run_mode = "remote"
        self.stack.setCurrentIndex(SCREEN_LOGIN)

    def _on_login_success(self, manager):
        self.credentials = manager
        # Fetch name, email, avatar from Google
        try:
            self.user_info = manager.get_user_info()
            print(f"[App] Logged in as: {self.user_info.get('name')} ({self.user_info.get('email')})")
        except Exception as e:
            print(f"[App] Could not fetch user info: {e}")
            self.user_info = {}
        self._launch_pipeline()

    def _launch_pipeline(self):
        if self.stack.count() > 2:
            old = self.stack.widget(2)
            self.stack.removeWidget(old)
            old.deleteLater()

        pipeline = PipelineScreen(
            run_mode=self.run_mode,
            credentials=self.credentials,
            user_info=self.user_info,
        )
        self.stack.addWidget(pipeline)
        self.stack.setCurrentIndex(SCREEN_PIPELINE)


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

    _load_fonts()

    win = AppWindow()
    win.show()
    sys.exit(app.exec())
import os
import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QFrame,
)
import qtawesome as qta

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont

from ui.styles.theme import (
    BG_SURFACE, BG_ELEVATED,
    BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW,
    NEON_GREEN, NEON_ORANGE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)

# Common install locations for Docker Desktop on Windows
_DOCKER_DESKTOP_PATHS = [
    r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
    r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Docker", "Docker Desktop.exe"),
]


def check_docker_running() -> bool:
    """Returns True if the Docker daemon is reachable (fast, < 1 s if not running)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=4,
        )
        return result.returncode == 0
    except Exception:
        return False


def find_docker_desktop() -> str | None:
    """Return the path to Docker Desktop.exe if found, else None."""
    for path in _DOCKER_DESKTOP_PATHS:
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------
# DockerStartDialog - shown when Docker is installed but not running
# ---------------------------------------------------------------------------

class DockerStartDialog(QDialog):
    """
    Tells the user Docker Desktop is not running and offers to start it.
    Polls every 2 s; auto-accepts once Docker is detected as running.
    """

    def __init__(self, docker_missing: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Docker Desktop required")
        self.setFixedWidth(480)
        self.setModal(True)
        self._docker_missing = docker_missing
        self._build_ui()

        if not docker_missing:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._check_docker)
            self._poll_timer.start(2_000)

    # -- UI -------------------------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 12px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(28, 24, 28, 22)

        # Icon + title row
        title_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("mdi.docker", color=CYAN).pixmap(QSize(36, 36)))
        title_row.addWidget(icon_lbl)
        title_row.addSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        if self._docker_missing:
            heading = QLabel("Docker Desktop not found")
        else:
            heading = QLabel("Docker Desktop is not running")
        heading.setFont(QFont("JetBrains Mono", 13, QFont.Bold))
        heading.setStyleSheet(f"color: {TEXT_PRIMARY};")
        title_col.addWidget(heading)

        sub = QLabel(
            "Docker must be installed to use Local mode."
            if self._docker_missing
            else "Please start Docker Desktop before continuing."
        )
        sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_col.addWidget(sub)
        title_row.addLayout(title_col, 1)
        root.addLayout(title_row)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: {BORDER}; border: none;")
        line.setFixedHeight(1)
        root.addWidget(line)

        if self._docker_missing:
            body = QLabel(
                "Docker Desktop was not found on this machine.\n\n"
                "Please install Docker Desktop from:\n"
                "  https://www.docker.com/products/docker-desktop\n\n"
                "After installing, restart Neural Forge and try again."
            )
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
            root.addWidget(body)
        else:
            body = QLabel(
                "Neural Forge detected that Docker Desktop is installed\n"
                "but the daemon is not running.\n\n"
                "Click  Start Docker Desktop  below, wait ~20 seconds for\n"
                "it to initialise, then this dialog will close automatically."
            )
            body.setWordWrap(True)
            body.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
            root.addWidget(body)

        # Status label (shown while waiting)
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._status_lbl.setVisible(not self._docker_missing)
        root.addWidget(self._status_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setFixedWidth(90)
        self._btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {BORDER_BRIGHT};
                border-radius: 6px; color: {TEXT_MUTED}; padding: 6px 12px;
            }}
            QPushButton:hover {{ border-color: {NEON_ORANGE}; color: {NEON_ORANGE}; }}
        """)
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_cancel)

        if not self._docker_missing:
            docker_path = find_docker_desktop()
            self._btn_start = QPushButton("Start Docker Desktop")
            self._btn_start.setFixedWidth(180)
            self._btn_start.setStyleSheet(f"""
                QPushButton {{
                    background: {CYAN}22; border: 1px solid {CYAN}88;
                    border-radius: 6px; color: {CYAN};
                    font-weight: bold; padding: 6px 12px;
                }}
                QPushButton:hover {{ background: {CYAN}44; border-color: {CYAN}; }}
                QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; background: transparent; }}
            """)
            if docker_path:
                self._btn_start.clicked.connect(lambda: self._start_docker(docker_path))
            else:
                self._btn_start.setEnabled(False)
                self._btn_start.setToolTip("Could not locate Docker Desktop.exe")
            btn_row.addWidget(self._btn_start)

        root.addLayout(btn_row)

    # -- Logic ----------------------------------------------------------------

    def _start_docker(self, path: str):
        try:
            subprocess.Popen([path])
            self._status_lbl.setText("Starting Docker Desktop… checking every 2 s")
            self._btn_start.setEnabled(False)
        except Exception as e:
            self._status_lbl.setText(f"Could not launch: {e}")
            self._status_lbl.setStyleSheet(f"color: {NEON_ORANGE}; font-size: 11px;")

    def _check_docker(self):
        if check_docker_running():
            self._poll_timer.stop()
            self._status_lbl.setText("Docker is running!")
            self._status_lbl.setStyleSheet(f"color: {NEON_GREEN}; font-size: 11px;")
            QTimer.singleShot(700, self.accept)

    def closeEvent(self, event):
        if hasattr(self, "_poll_timer"):
            self._poll_timer.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# DockerWarningDialog - prerequisite checklist (shown once per install)
# ---------------------------------------------------------------------------

class DockerWarningDialog(QDialog):
    """
    Modal dialog shown before the user enters Local mode.
    Explains that Docker must be installed and running.
    The user can tick 'do not show again' to suppress it in future sessions.
    """

    PREF_KEY = "docker_warning_dismissed"

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Local Mode  -  Prerequisites")
        self.setFixedWidth(480)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(24, 24, 24, 20)

        header = QLabel("Docker is required for Local mode")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        header.setFont(font)
        root.addWidget(header)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        body = QLabel(
            "Before using Local mode please make sure that:\n\n"
            "  1.  Docker Desktop is installed on your machine.\n"
            "  2.  Docker Desktop is currently running\n"
            "       (the Docker icon is visible in your system tray).\n"
            "  3.  You have at least 72 GB of free disk space for\n"
            "       the pipeline image.\n\n"
            "If Docker is not running the pipeline container will fail\n"
            "to start and no results will be produced.\n\n"
            "Download Docker Desktop:  https://www.docker.com/products/docker-desktop"
        )
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(body)

        self._checkbox = QCheckBox("Do not show this message again")
        root.addWidget(self._checkbox)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setFixedWidth(90)
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_cancel)

        self._btn_continue = QPushButton("Continue to Local")
        self._btn_continue.setFixedWidth(140)
        self._btn_continue.setDefault(True)
        self._btn_continue.clicked.connect(self._on_continue)
        btn_row.addWidget(self._btn_continue)

        root.addLayout(btn_row)

    def _on_continue(self):
        if self._checkbox.isChecked():
            self._settings.setValue(self.PREF_KEY, True)
        self.accept()

    # -- Static helpers -------------------------------------------------------

    @staticmethod
    def should_show(settings) -> bool:
        return not settings.value(DockerWarningDialog.PREF_KEY, False, type=bool)

    @staticmethod
    def run_if_needed(settings, parent=None) -> bool:
        if not DockerWarningDialog.should_show(settings):
            return True
        dlg = DockerWarningDialog(settings, parent)
        return dlg.exec() == QDialog.Accepted

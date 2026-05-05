from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap, QIcon
import os


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

        # Header
        header = QLabel("Docker is required for Local mode")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        header.setFont(font)
        root.addWidget(header)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # Body text
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

        # Checkbox
        self._checkbox = QCheckBox("Do not show this message again")
        root.addWidget(self._checkbox)

        # Buttons
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

    # -- Static entry point ----------------------------------------------------

    @staticmethod
    def should_show(settings) -> bool:
        """Returns True if the dialog should be shown (user has not dismissed it)."""
        return not settings.value(DockerWarningDialog.PREF_KEY, False, type=bool)

    @staticmethod
    def run_if_needed(settings, parent=None) -> bool:
        """
        Shows the dialog if needed.
        Returns True if the user confirmed (or the dialog was suppressed),
        False if the user clicked Cancel.
        """
        if not DockerWarningDialog.should_show(settings):
            return True
        dlg = DockerWarningDialog(settings, parent)
        return dlg.exec() == QDialog.Accepted
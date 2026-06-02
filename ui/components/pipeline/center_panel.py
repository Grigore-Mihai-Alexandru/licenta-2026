import html as _html

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QFrame,
)
import qtawesome as qta

from PySide6.QtCore import Qt, Signal, QTimer, QSize

from ui.styles.theme import (
    BG_ELEVATED, BG_SURFACE, BORDER,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_MUTED, TEXT_SECONDARY, TEXT_PRIMARY,
)
from ui.components.pipeline.constants import IDLE
from ui.components.pipeline.helpers import section_label, card
from ui.components.pipeline.step_widget import StepWidget, StepConnector

# Drive states - auth states handled in TopBar, center only shows upload states
_DRIVE_STATES = {"connect", "connecting", "connected", "ready", "uploading", "done"}


class CenterPanel(QWidget):
    cancel_requested          = Signal()
    upload_to_drive_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_widgets: list = []
        self._build()

    # Public API

    def set_step_state(self, index: int, state: str):
        if 0 <= index < len(self.step_widgets):
            self.step_widgets[index].set_state(state)

    def set_all_steps(self, state: str):
        for sw in self.step_widgets:
            sw.set_state(state)

    def log(self, message: str, color: str = None):
        safe = _html.escape(message)
        if color:
            self._log_widget.append(f'<span style="color:{color}">{safe}</span>')
        else:
            self._log_widget.append(safe)
        sb = self._log_widget.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_job_status(self, text: str, color: str):
        self.job_status_lbl.setText(text)
        self.job_status_lbl.setStyleSheet(f"""
            color: {color}; font-size: 15px;
            font-family: 'JetBrains Mono', monospace;
        """)

    def set_job_id(self, text: str):
        self.job_id_lbl.setText(text)

    def show_cancel_button(self, visible: bool):
        self.btn_cancel.setVisible(visible)

    def set_cancel_label(self, text: str):
        self.btn_cancel.setText(text)

    def set_drive_state(self, state: str, n_files: int = 0, **_):
        """
        Update the Drive upload section.
          connect / connecting / connected - not ready, show nothing actionable
          ready     - show Upload button
          uploading - show progress text
          done      - show success text
        """
        assert state in _DRIVE_STATES, f"Unknown drive state: {state}"

        self._drive_upload_btn.setVisible(state == "ready")
        self._drive_upload_lbl.setVisible(state in {"uploading", "done"})
        self._drive_not_connected_lbl.setVisible(state in {"connect", "connecting"})

        if state == "ready":
            self._drive_upload_btn.setText(
                f"Upload to Drive  ({n_files} file{'s' if n_files != 1 else ''})"
            )
            self._drive_upload_btn.setEnabled(True)
        elif state == "connected":
            # Authenticated but no results yet - nothing to show
            pass
        elif state == "connecting":
            self._drive_not_connected_lbl.setText("Connecting to Drive…")
            self._drive_not_connected_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        elif state == "connect":
            self._drive_not_connected_lbl.setText("Connect Drive via the button above ↑")
            self._drive_not_connected_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        elif state == "uploading":
            self._drive_upload_lbl.setText("Uploading to Drive…")
            self._drive_upload_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        elif state == "done":
            self._drive_upload_lbl.setText("Saved to Drive")
            self._drive_upload_lbl.setStyleSheet(
                f"color: {NEON_GREEN}; font-size: 13px; font-weight: bold;"
            )

    # Build

    def _build(self):
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        # PIPELINE STEPS
        col.addWidget(section_label("PIPELINE STEPS"))
        col.addSpacing(4)

        steps_card   = card()
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(8, 12, 8, 12)
        steps_layout.setSpacing(0)

        for i, (num, name, sub, letter) in enumerate([
            (1, "RESTORMER", "Image denoising",     "R"),
            (2, "WONDER3D",  "3D model generation", "W"),
            (3, "MESH OPT",  "LOD generation",      "M"),
        ]):
            sw = StepWidget(num, name, sub, letter)
            self.step_widgets.append(sw)
            steps_layout.addWidget(sw)
            if i < 2:
                steps_layout.addWidget(StepConnector())

        col.addWidget(steps_card)
        col.addSpacing(8)

        # JOB STATUS
        col.addWidget(section_label("JOB STATUS"))
        col.addSpacing(4)

        status_card = card()
        status_lay  = QVBoxLayout(status_card)
        status_lay.setContentsMargins(16, 12, 16, 12)
        status_lay.setSpacing(8)

        self.job_status_lbl = QLabel("No job running")
        self.job_status_lbl.setStyleSheet(f"""
            color: {TEXT_MUTED}; font-size: 15px;
            font-family: 'JetBrains Mono', monospace;
        """)
        status_lay.addWidget(self.job_status_lbl)

        self.job_id_lbl = QLabel("")
        self.job_id_lbl.setWordWrap(True)
        self.job_id_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        status_lay.addWidget(self.job_id_lbl)

        self.btn_cancel = QPushButton("Cancel Job")
        self.btn_cancel.setIcon(qta.icon("mdi.close-circle", color=NEON_ORANGE))
        self.btn_cancel.setIconSize(QSize(16, 16))
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {NEON_ORANGE}18; border: 1px solid {NEON_ORANGE}88;
                border-radius: 8px; color: {NEON_ORANGE};
                font-size: 13px; font-weight: bold; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {NEON_ORANGE}33; border-color: {NEON_ORANGE}; }}
            QPushButton:pressed {{ background: {NEON_ORANGE}44; }}
        """)
        self.btn_cancel.clicked.connect(self.cancel_requested)
        status_lay.addWidget(self.btn_cancel)

        col.addWidget(status_card)
        col.addSpacing(8)

        # GOOGLE DRIVE
        col.addWidget(section_label("GOOGLE DRIVE"))
        col.addSpacing(4)

        drive_card = card()
        drive_lay  = QVBoxLayout(drive_card)
        drive_lay.setContentsMargins(16, 14, 16, 14)
        drive_lay.setSpacing(8)

        # Hint shown when Drive is not connected (points to top-bar button)
        self._drive_not_connected_lbl = QLabel("Connect Drive via the button above ↑")
        self._drive_not_connected_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        drive_lay.addWidget(self._drive_not_connected_lbl)

        # Upload button - shown when results are ready and Drive is connected
        self._drive_upload_btn = QPushButton("Upload to Drive")
        self._drive_upload_btn.setIcon(qta.icon("mdi.cloud-upload", color=PURPLE))
        self._drive_upload_btn.setIconSize(QSize(16, 16))
        self._drive_upload_btn.setFixedHeight(40)
        self._drive_upload_btn.setVisible(False)
        self._drive_upload_btn.setCursor(Qt.PointingHandCursor)
        self._drive_upload_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PURPLE}22; border: 1px solid {PURPLE};
                border-radius: 8px; color: {PURPLE};
                font-size: 15px; font-weight: bold; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {PURPLE}44; }}
            QPushButton:disabled {{
                border-color: {BORDER}; color: {TEXT_MUTED}; background: transparent;
            }}
        """)
        self._drive_upload_btn.clicked.connect(self.upload_to_drive_requested)
        drive_lay.addWidget(self._drive_upload_btn)

        # Status label - uploading / done
        self._drive_upload_lbl = QLabel("")
        self._drive_upload_lbl.setVisible(False)
        self._drive_upload_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        drive_lay.addWidget(self._drive_upload_lbl)

        col.addWidget(drive_card)
        col.addSpacing(8)

        # LOG OUTPUT
        col.addWidget(section_label("LOG OUTPUT"))
        col.addSpacing(4)

        log_card = card()
        log_lay  = QVBoxLayout(log_card)
        log_lay.setContentsMargins(0, 0, 0, 0)

        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setPlaceholderText("Pipeline logs will appear here...")
        self._log_widget.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; border: none;
                border-radius: 12px; color: {TEXT_SECONDARY};
                font-size: 13px; padding: 12px;
            }}
        """)
        log_lay.addWidget(self._log_widget)
        col.addWidget(log_card, 1)

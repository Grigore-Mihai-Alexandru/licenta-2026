from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit,
)
from PySide6.QtCore import Signal

from ui.styles.theme import (
    BG_SURFACE, BORDER,
    CYAN,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_MUTED, TEXT_SECONDARY,
)
from ui.components.pipeline.constants import IDLE
from ui.components.pipeline.helpers import section_label, card
from ui.components.pipeline.step_widget import StepWidget, StepConnector


class CenterPanel(QWidget):
    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_widgets: list = []
        self._build()

    # -- Public API ------------------------------------------------------------

    def set_step_state(self, index: int, state: str):
        if 0 <= index < len(self.step_widgets):
            self.step_widgets[index].set_state(state)

    def set_all_steps(self, state: str):
        for sw in self.step_widgets:
            sw.set_state(state)

    def log(self, message: str, color: str = None):
        if color:
            self._log_widget.append(f'<span style="color:{color}">{message}</span>')
        else:
            self._log_widget.append(message)
        sb = self._log_widget.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_job_status(self, text: str, color: str):
        self.job_status_lbl.setText(text)
        self.job_status_lbl.setStyleSheet(f"""
            color: {color}; font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
        """)

    def set_job_id(self, text: str):
        self.job_id_lbl.setText(text)

    def show_save_button(self, visible: bool, n_files: int = 0):
        self.btn_save.setVisible(visible)
        if visible and n_files:
            self.btn_save.setText(f"Save to Drive  ({n_files} files)")

    def set_save_enabled(self, enabled: bool):
        self.btn_save.setEnabled(enabled)

    # -- Build -----------------------------------------------------------------

    def _build(self):
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        col.addWidget(section_label("PIPELINE STEPS"))
        col.addSpacing(4)

        steps_card   = card()
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(8, 12, 8, 12)
        steps_layout.setSpacing(0)

        steps_data = [
            (1, "RESTORMER", "Image denoising",     "R"),
            (2, "WONDER3D",  "3D model generation", "W"),
            (3, "MESH OPT",  "LOD generation",      "M"),
        ]
        for i, (num, name, sub, letter) in enumerate(steps_data):
            sw = StepWidget(num, name, sub, letter)
            self.step_widgets.append(sw)
            steps_layout.addWidget(sw)
            if i < len(steps_data) - 1:
                steps_layout.addWidget(StepConnector())

        col.addWidget(steps_card)
        col.addSpacing(8)

        col.addWidget(section_label("JOB STATUS"))
        col.addSpacing(4)

        status_card = card()
        status_lay  = QVBoxLayout(status_card)
        status_lay.setContentsMargins(16, 12, 16, 12)
        status_lay.setSpacing(8)

        self.job_status_lbl = QLabel("No job running")
        self.job_status_lbl.setStyleSheet(f"""
            color: {TEXT_MUTED}; font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
        """)
        status_lay.addWidget(self.job_status_lbl)

        self.job_id_lbl = QLabel("")
        self.job_id_lbl.setWordWrap(True)
        self.job_id_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        status_lay.addWidget(self.job_id_lbl)

        self.btn_save = QPushButton("Save to Drive")
        self.btn_save.setFixedHeight(40)
        self.btn_save.setVisible(False)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {PURPLE}22; border: 1px solid {PURPLE};
                border-radius: 8px; color: {PURPLE};
                font-size: 12px; font-weight: bold; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {PURPLE}44; }}
            QPushButton:disabled {{ border-color: {BORDER}; color: {TEXT_MUTED}; background: transparent; }}
        """)
        self.btn_save.clicked.connect(self.save_requested)
        status_lay.addWidget(self.btn_save)

        col.addWidget(status_card)
        col.addSpacing(8)

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
                font-size: 11px; padding: 12px;
            }}
        """)
        log_lay.addWidget(self._log_widget)
        col.addWidget(log_card, 1)

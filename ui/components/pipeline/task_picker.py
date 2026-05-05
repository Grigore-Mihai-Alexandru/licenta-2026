from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QDialog,
)
from PySide6.QtCore import Qt

from ui.styles.theme import (
    BG_ELEVATED, BG_SURFACE,
    BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    TEXT_PRIMARY, TEXT_MUTED,
)
from ui.components.pipeline.constants import RESTORMER_TASKS


class TaskPickerDialog(QDialog):
    """Floating checklist popup for Restormer task selection."""

    def __init__(self, selected: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Restormer Tasks")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 10px;
            }}
        """)
        self.setFixedWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QLabel("RESTORMER TASKS")
        header.setStyleSheet(f"""
            color: {TEXT_MUTED}; font-size: 10px;
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 3px; font-weight: bold;
        """)
        layout.addWidget(header)

        self.checkboxes: dict = {}
        for task in RESTORMER_TASKS:
            cb = QCheckBox(task)
            cb.setChecked(task in selected)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {TEXT_PRIMARY};
                    font-size: 12px;
                    font-family: 'JetBrains Mono', monospace;
                    padding: 4px 2px;
                }}
                QCheckBox::indicator {{
                    width: 15px; height: 15px;
                    border: 1px solid {BORDER_BRIGHT};
                    border-radius: 3px;
                    background: {BG_SURFACE};
                }}
                QCheckBox::indicator:checked {{
                    background: {CYAN};
                    border-color: {CYAN};
                }}
                QCheckBox:hover {{ color: {CYAN}; }}
            """)
            layout.addWidget(cb)
            self.checkboxes[task] = cb

        btn_ok = QPushButton("Confirm")
        btn_ok.setFixedHeight(34)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {CYAN_GLOW};
                border: 1px solid {CYAN_DIM};
                border-radius: 6px;
                color: {CYAN};
                font-size: 12px; font-weight: bold;
                margin-top: 4px;
            }}
            QPushButton:hover {{ background: {CYAN}33; }}
        """)
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

    def selected_tasks(self) -> list:
        return [t for t, cb in self.checkboxes.items() if cb.isChecked()]


class TaskPickerButton(QWidget):
    """Button that summarises selected tasks and opens TaskPickerDialog on click."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = ["Real_Denoising"]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.btn = QPushButton()
        self.btn.setFixedHeight(36)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 6px;
                color: {TEXT_PRIMARY};
                padding: 6px 10px;
                font-size: 12px;
                font-family: 'JetBrains Mono', monospace;
                text-align: left;
            }}
            QPushButton:hover {{ border-color: {CYAN}; color: {CYAN}; }}
        """)
        self.btn.clicked.connect(self._open_picker)
        layout.addWidget(self.btn)

        self._refresh_label()

    def _refresh_label(self):
        if not self._selected:
            self.btn.setText("None selected  v")
        elif len(self._selected) == 1:
            self.btn.setText(f"{self._selected[0]}  v")
        else:
            self.btn.setText(f"{len(self._selected)} tasks selected  v")

    def _open_picker(self):
        dlg = TaskPickerDialog(self._selected, parent=self)
        pos = self.btn.mapToGlobal(self.btn.rect().bottomLeft())
        dlg.move(pos)
        if dlg.exec():
            result = dlg.selected_tasks()
            if result:
                self._selected = result
            self._refresh_label()

    def selected_tasks(self) -> list:
        return list(self._selected)

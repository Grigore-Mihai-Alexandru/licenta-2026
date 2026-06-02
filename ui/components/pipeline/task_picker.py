from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QDialog, QFrame,
)
import qtawesome as qta

from PySide6.QtCore import Qt, QSize

from ui.styles.theme import (
    BG_ELEVATED, BG_SURFACE,
    BORDER_BRIGHT, BORDER,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_ORANGE,
    TEXT_PRIMARY, TEXT_MUTED,
)
from ui.components.pipeline.constants import RESTORMER_TASKS

_GRAY_TASKS = {"Gaussian_Gray_Denoising"}


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
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        header = QLabel("RESTORMER TASKS")
        header.setStyleSheet(f"""
            color: {TEXT_MUTED}; font-size: 13px;
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 3px; font-weight: bold;
        """)
        layout.addWidget(header)

        self.checkboxes: dict = {}
        _added_gray_divider = False
        for task in RESTORMER_TASKS:
            if task in _GRAY_TASKS and not _added_gray_divider:
                div = QFrame()
                div.setFixedHeight(1)
                div.setStyleSheet(f"background: {BORDER}; border: none;")
                layout.addWidget(div)
                note_row = QHBoxLayout()
                note_row.setSpacing(6)
                note_row.setContentsMargins(0, 0, 0, 0)
                warn_icon_lbl = QLabel()
                warn_icon_lbl.setPixmap(
                    qta.icon("mdi.alert", color=NEON_ORANGE).pixmap(QSize(14, 14))
                )
                note_row.addWidget(warn_icon_lbl)
                note_txt_lbl = QLabel("Grayscale output - runs first in chain")
                note_txt_lbl.setStyleSheet(
                    f"color: {NEON_ORANGE}; font-size: 12px; "
                    f"font-family: 'JetBrains Mono', monospace; padding: 2px 0;"
                )
                note_row.addWidget(note_txt_lbl)
                note_row.addStretch()
                layout.addLayout(note_row)
                _added_gray_divider = True

            cb = QCheckBox(task)
            cb.setChecked(task in selected)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {TEXT_PRIMARY};
                    font-size: 15px;
                    font-family: 'JetBrains Mono', monospace;
                    padding: 5px 2px;
                }}
                QCheckBox::indicator {{
                    width: 18px; height: 18px;
                    border: 1px solid {BORDER_BRIGHT};
                    border-radius: 4px;
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
        btn_ok.setFixedHeight(42)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {CYAN_GLOW};
                border: 1px solid {CYAN_DIM};
                border-radius: 6px;
                color: {CYAN};
                font-size: 15px; font-weight: bold;
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
        self.btn.setFixedHeight(42)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 6px;
                color: {TEXT_PRIMARY};
                padding: 8px 12px;
                font-size: 15px;
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

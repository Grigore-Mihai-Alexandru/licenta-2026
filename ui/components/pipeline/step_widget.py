from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor

from ui.styles.theme import (
    BG_ELEVATED, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)
from ui.components.pipeline.constants import IDLE, RUNNING, DONE, ERROR


class StepWidget(QWidget):
    def __init__(self, number: int, name: str, subtitle: str, run_letter: str, parent=None):
        super().__init__(parent)
        self.number      = number
        self._state      = IDLE
        self._run_letter = run_letter

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        self.circle = QLabel()
        self.circle.setFixedSize(44, 44)
        self.circle.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.circle)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.name_lbl = QLabel(name)
        self.name_lbl.setStyleSheet(f"""
            font-size: 16px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace;
            color: {TEXT_PRIMARY};
        """)
        text_col.addWidget(self.name_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED};")
        text_col.addWidget(self.sub_lbl)

        layout.addLayout(text_col)
        layout.addStretch()

        self.badge = QLabel("IDLE")
        self.badge.setFixedWidth(70)
        self.badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.badge)

        self._refresh()

    def set_state(self, state: str):
        self._state = state
        self._refresh()

    def _refresh(self):
        s = self._state
        if s == IDLE:
            circle_bg    = BG_ELEVATED
            circle_color = TEXT_MUTED
            badge_text   = "IDLE"
            badge_color  = TEXT_MUTED
            circle_txt   = str(self.number)
        elif s == RUNNING:
            circle_bg    = CYAN_GLOW
            circle_color = CYAN
            badge_text   = "RUNNING"
            badge_color  = CYAN
            circle_txt   = self._run_letter
        elif s == DONE:
            circle_bg    = f"{NEON_GREEN}22"
            circle_color = NEON_GREEN
            badge_text   = "DONE"
            badge_color  = NEON_GREEN
            circle_txt   = "OK"
        else:
            circle_bg    = f"{NEON_ORANGE}22"
            circle_color = NEON_ORANGE
            badge_text   = "ERROR"
            badge_color  = NEON_ORANGE
            circle_txt   = "X"

        self.circle.setText(circle_txt)
        self.circle.setStyleSheet(f"""
            background-color: {circle_bg};
            border: 2px solid {circle_color};
            border-radius: 22px;
            color: {circle_color};
            font-size: 16px; font-weight: bold;
        """)
        self.badge.setText(badge_text)
        self.badge.setStyleSheet(f"""
            color: {badge_color}; background: {badge_color}22;
            border: 1px solid {badge_color}55;
            border-radius: 6px;
            font-size: 12px; font-weight: bold;
            letter-spacing: 1px; padding: 3px 8px;
        """)
        name_color = TEXT_PRIMARY if s != IDLE else TEXT_SECONDARY
        self.name_lbl.setStyleSheet(f"""
            font-size: 16px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace;
            color: {name_color};
        """)


class StepConnector(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QColor(BORDER_BRIGHT))
        cx = self.width() // 2
        p.drawLine(cx, 0, cx, self.height())
        p.end()

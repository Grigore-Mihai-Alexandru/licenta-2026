import urllib.request

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPainterPath

from ui.styles.theme import (
    BG_SURFACE, BORDER,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN,
    TEXT_PRIMARY, TEXT_MUTED,
)


class TopBar(QWidget):
    def __init__(self, run_mode: str, user_info: dict = None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet(f"""
            background-color: {BG_SURFACE};
            border-bottom: 1px solid {BORDER};
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        logo = QLabel("⬡ NEURAL FORGE")
        logo.setStyleSheet(f"""
            color: {CYAN}; font-size: 14px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace; letter-spacing: 2px;
        """)
        layout.addWidget(logo)
        layout.addStretch()

        mode_color = NEON_GREEN if run_mode == "local" else CYAN
        mode_text  = "LOCAL" if run_mode == "local" else "CLOUD"
        mode_badge = QLabel(f"● {mode_text}")
        mode_badge.setStyleSheet(f"""
            color: {mode_color}; background: {mode_color}22;
            border: 1px solid {mode_color}55;
            border-radius: 10px; padding: 4px 12px;
            font-size: 11px; font-weight: bold; letter-spacing: 1px;
        """)
        layout.addWidget(mode_badge)

        if user_info and user_info.get("email"):
            layout.addSpacing(8)

            self.avatar = QLabel()
            self.avatar.setFixedSize(32, 32)
            self.avatar.setAlignment(Qt.AlignCenter)
            self._set_avatar_initials(user_info.get("name", "?"))
            layout.addWidget(self.avatar)

            if user_info.get("picture"):
                self._load_avatar(user_info["picture"])

            user_col = QVBoxLayout()
            user_col.setSpacing(0)

            name_lbl = QLabel(user_info.get("name", ""))
            name_lbl.setStyleSheet(f"""
                font-size: 12px; font-weight: bold;
                color: {TEXT_PRIMARY}; font-family: 'JetBrains Mono', monospace;
            """)
            user_col.addWidget(name_lbl)

            email_lbl = QLabel(user_info.get("email", ""))
            email_lbl.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            user_col.addWidget(email_lbl)

            layout.addLayout(user_col)

    def _set_avatar_initials(self, name: str):
        initials = "".join(p[0].upper() for p in name.split()[:2]) or "?"
        self.avatar.setText(initials)
        self.avatar.setStyleSheet(f"""
            background: {CYAN_GLOW}; border: 1px solid {CYAN_DIM};
            border-radius: 16px; color: {CYAN};
            font-size: 12px; font-weight: bold;
        """)

    def _load_avatar(self, url: str):
        try:
            data = urllib.request.urlopen(url, timeout=3).read()
            px   = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                px      = px.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                rounded = QPixmap(32, 32)
                rounded.fill(Qt.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.Antialiasing)
                path = QPainterPath()
                path.addEllipse(0, 0, 32, 32)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, px)
                painter.end()
                self.avatar.setPixmap(rounded)
                self.avatar.setStyleSheet("border-radius: 16px;")
        except Exception:
            pass

import urllib.request

import qtawesome as qta

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QMenu
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QFont, QCursor

from ui.styles.theme import (
    BG_SURFACE, BG_ELEVATED, BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)

_NAV_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        color: {TEXT_MUTED};
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        font-weight: bold;
        letter-spacing: 1px;
        padding: 4px 12px;
    }}
    QPushButton:hover {{
        color: {CYAN};
        border-color: {CYAN}55;
        background: {CYAN}11;
    }}
    QPushButton:pressed {{ background: {CYAN}22; }}
"""

_MENU_STYLE = f"""
    QMenu {{
        background-color: {BG_ELEVATED};
        border: 1px solid {BORDER_BRIGHT};
        border-radius: 10px;
        padding: 6px 4px;
        color: {TEXT_PRIMARY};
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
    }}
    QMenu::item {{
        padding: 7px 18px;
        border-radius: 6px;
        margin: 1px 4px;
    }}
    QMenu::item:selected {{
        background: {CYAN}22;
        color: {CYAN};
    }}
    QMenu::item:disabled {{
        color: {TEXT_MUTED};
        background: transparent;
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER_BRIGHT};
        margin: 5px 8px;
    }}
"""


class TopBar(QWidget):
    home_requested         = Signal()
    history_requested      = Signal()
    sign_out_requested     = Signal()          # cloud: full sign-out
    connect_drive_requested    = Signal()      # local: connect Drive from top bar
    disconnect_drive_requested = Signal()      # local: disconnect Drive from top bar

    def __init__(self, run_mode: str, user_info: dict = None, parent=None):
        super().__init__(parent)
        self._run_mode    = run_mode
        self._user_info   = user_info or {}
        self._drive_email = ""
        self._drive_connected = False

        self.setFixedHeight(54)
        self.setStyleSheet(f"""
            background-color: {BG_SURFACE};
            border-bottom: 1px solid {BORDER};
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 20, 8)
        layout.setSpacing(8)

        # Home
        btn_home = QPushButton("HOME")
        btn_home.setIcon(qta.icon("mdi.home", color=TEXT_MUTED))
        btn_home.setIconSize(QSize(16, 16))
        btn_home.setCursor(Qt.PointingHandCursor)
        btn_home.setStyleSheet(_NAV_BTN_STYLE)
        btn_home.clicked.connect(self.home_requested)
        layout.addWidget(btn_home)

        sep = QLabel("|")
        sep.setStyleSheet(f"color: {BORDER}; font-size: 16px;")
        layout.addWidget(sep)

        logo = QLabel("⬡ PHOTO2SOLID")
        logo.setStyleSheet(f"""
            color: {CYAN}; font-size: 14px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace; letter-spacing: 2px;
        """)
        layout.addWidget(logo)
        layout.addStretch()

        # History
        btn_history = QPushButton("HISTORY")
        btn_history.setCursor(Qt.PointingHandCursor)
        btn_history.setStyleSheet(_NAV_BTN_STYLE)
        btn_history.clicked.connect(self.history_requested)
        layout.addWidget(btn_history)

        layout.addSpacing(4)

        # Mode badge
        mode_color = NEON_GREEN if run_mode == "local" else CYAN
        mode_text  = "LOCAL" if run_mode == "local" else "CLOUD"
        mode_badge = QLabel(mode_text)
        mode_badge.setStyleSheet(f"""
            color: {mode_color}; background: {mode_color}22;
            border: 1px solid {mode_color}55;
            border-radius: 10px; padding: 4px 12px;
            font-size: 13px; font-weight: bold; letter-spacing: 1px;
        """)
        layout.addWidget(mode_badge)

        layout.addSpacing(8)

        # Right widget: cloud user OR local Drive status
        if run_mode == "remote" and self._user_info.get("email"):
            self._build_user_widget(layout)
        elif run_mode == "local":
            self._build_drive_widget(layout)

    # Cloud user widget

    def _build_user_widget(self, layout):
        info = self._user_info

        self._avatar_btn = QPushButton()
        self._avatar_btn.setFixedSize(36, 36)
        self._avatar_btn.setCursor(Qt.PointingHandCursor)
        self._avatar_btn.setStyleSheet(f"""
            QPushButton {{
                background: {CYAN_GLOW};
                border: 2px solid {CYAN_DIM};
                border-radius: 18px;
                color: {CYAN};
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {CYAN};
                background: {CYAN}33;
            }}
        """)
        initials = "".join(p[0].upper() for p in info.get("name", "?").split()[:2]) or "?"
        self._avatar_btn.setText(initials)
        self._avatar_btn.clicked.connect(self._show_user_menu)
        layout.addWidget(self._avatar_btn)

        if info.get("picture"):
            self._load_avatar(info["picture"])

    def _show_user_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        info = self._user_info
        name_act = QAction(info.get("name", ""), menu)
        name_act.setEnabled(False)
        menu.addAction(name_act)

        email_act = QAction(info.get("email", ""), menu)
        email_act.setEnabled(False)
        menu.addAction(email_act)

        menu.addSeparator()

        signout_act = QAction("Sign Out", menu)
        signout_act.setIcon(qta.icon("mdi.logout", color=NEON_ORANGE))
        signout_act.triggered.connect(self.sign_out_requested)
        menu.addAction(signout_act)

        btn = self._avatar_btn
        pos = btn.mapToGlobal(QPoint(0, btn.height() + 4))
        menu.exec_(pos)

    # Local Drive widget

    def _build_drive_widget(self, layout):
        self._drive_btn = QPushButton("Connect Drive")
        self._drive_btn.setIcon(qta.icon("mdi.google-drive", color=PURPLE))
        self._drive_btn.setIconSize(QSize(16, 16))
        self._drive_btn.setFixedHeight(34)
        self._drive_btn.setCursor(Qt.PointingHandCursor)
        self._drive_btn.clicked.connect(self._on_drive_btn_clicked)
        self._apply_drive_btn_style(connected=False)
        layout.addWidget(self._drive_btn)

    def _apply_drive_btn_style(self, connected: bool):
        if connected:
            self._drive_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {NEON_GREEN}18;
                    border: 1px solid {NEON_GREEN}66;
                    border-radius: 8px;
                    color: {NEON_GREEN};
                    font-size: 13px;
                    font-weight: bold;
                    padding: 4px 12px;
                    font-family: 'JetBrains Mono', monospace;
                }}
                QPushButton:hover {{
                    background: {NEON_GREEN}30;
                    border-color: {NEON_GREEN};
                }}
            """)
        else:
            self._drive_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {PURPLE}18;
                    border: 1px solid {PURPLE}88;
                    border-radius: 8px;
                    color: {PURPLE};
                    font-size: 13px;
                    font-weight: bold;
                    padding: 4px 12px;
                    font-family: 'JetBrains Mono', monospace;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    background: {PURPLE}33;
                    border-color: {PURPLE};
                }}
            """)

    def _on_drive_btn_clicked(self):
        if self._drive_connected:
            self._show_drive_menu()
        else:
            self.connect_drive_requested.emit()

    def _show_drive_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        title_act = QAction("Google Drive", menu)
        title_act.setEnabled(False)
        menu.addAction(title_act)

        email_act = QAction(self._drive_email or "Connected", menu)
        email_act.setEnabled(False)
        menu.addAction(email_act)

        menu.addSeparator()

        disc_act = QAction("Disconnect Drive", menu)
        disc_act.setIcon(qta.icon("mdi.link-off", color=NEON_ORANGE))
        disc_act.triggered.connect(self.disconnect_drive_requested)
        menu.addAction(disc_act)

        pos = self._drive_btn.mapToGlobal(QPoint(0, self._drive_btn.height() + 4))
        menu.exec_(pos)

    def set_drive_connected(self, email: str):
        """Call after successful Drive auth (local mode)."""
        if not hasattr(self, "_drive_btn"):
            return
        self._drive_connected = True
        self._drive_email = email
        short = email if len(email) <= 24 else email[:21] + "…"
        self._drive_btn.setIcon(qta.icon("mdi.google-drive", color=NEON_GREEN))
        self._drive_btn.setIconSize(QSize(16, 16))
        self._drive_btn.setText(short)
        self._apply_drive_btn_style(connected=True)

    def set_drive_disconnected(self):
        """Call after Drive disconnect (local mode)."""
        if not hasattr(self, "_drive_btn"):
            return
        self._drive_connected = False
        self._drive_email = ""
        self._drive_btn.setIcon(qta.icon("mdi.google-drive", color=PURPLE))
        self._drive_btn.setIconSize(QSize(16, 16))
        self._drive_btn.setText("Connect Drive")
        self._apply_drive_btn_style(connected=False)

    # Avatar helpers

    def _load_avatar(self, url: str):
        try:
            data = urllib.request.urlopen(url, timeout=3).read()
            px   = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                px      = px.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                rounded = QPixmap(36, 36)
                rounded.fill(Qt.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.Antialiasing)
                path = QPainterPath()
                path.addEllipse(0, 0, 36, 36)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, px)
                painter.end()
                self._avatar_btn.setIcon(rounded)  # type: ignore
                from PySide6.QtCore import QSize
                self._avatar_btn.setIconSize(QSize(36, 36))
                self._avatar_btn.setText("")
                self._avatar_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: 2px solid {CYAN_DIM};
                        border-radius: 18px;
                    }}
                    QPushButton:hover {{ border-color: {CYAN}; }}
                """)
        except Exception:
            pass

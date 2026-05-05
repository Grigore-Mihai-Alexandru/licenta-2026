# login_screen.py — Google OAuth login screen (remote/cloud mode)

import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGraphicsDropShadowEffect, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject
from PySide6.QtGui import QFont, QColor

_TOKEN_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "cloud", "token.pickle")
)

from ui.styles.theme import (
    BG_SURFACE, BG_ELEVATED,
    BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
)
from ui.icons import CloudUploadIcon


class AuthWorker(QObject):
    """Runs CloudManager.authenticate() in a background thread."""
    success = Signal(object)   # emits CloudManager instance
    error   = Signal(str)      # emits error message

    def __init__(self):
        super().__init__()
        cloud_dir = os.path.join(os.path.dirname(__file__), "..", "..", "cloud")
        cloud_dir = os.path.abspath(cloud_dir)
        if cloud_dir not in sys.path:
            sys.path.insert(0, cloud_dir)

    def run(self):
        try:
            from CloudManager import CloudManager
            import pickle
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow

            manager = CloudManager(
                client_secrets_path=os.path.join(
                    os.path.dirname(__file__), "..", "..", "cloud", "client_secrets.json"
                )
            )
            token_path = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "..", "cloud", "token.pickle"
            ))

            creds = None

            # Load existing token if present
            if os.path.exists(token_path):
                with open(token_path, "rb") as f:
                    creds = pickle.load(f)

            # If the saved token is missing required scopes, discard it so a
            # fresh browser auth is triggered (picks up any newly added scopes).
            if creds and creds.scopes:
                required = {"https://www.googleapis.com/auth/userinfo.email", "openid"}
                if not required.issubset(creds.scopes):
                    creds = None

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        # Token revoked or expired — force fresh browser login
                        creds = None

                if not creds:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        manager.client_secrets, manager.scopes
                    )
                    creds = flow.run_local_server(port=0)

                # Save updated token
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)

            manager.creds = creds
            self.success.emit(manager)

        except Exception as e:
            self.error.emit(str(e))


class LoginScreen(QWidget):
    """
    Signals:
        login_success(CloudManager)  — emitted after successful Google auth
        back_requested               — user clicked Back
    """
    login_success  = Signal(object)
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._auto_triggered = False
        self._build()

    def showEvent(self, event):
        super().showEvent(event)
        # If a saved token exists, skip the button and authenticate silently.
        if os.path.exists(_TOKEN_PATH) and not self._auto_triggered:
            self._auto_triggered = True
            QTimer.singleShot(120, self._on_login)

    def _build(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)
        root.setSpacing(0)
        root.setContentsMargins(60, 60, 60, 60)

        # --- Back button ---
        back_row = QHBoxLayout()
        self.btn_back = QPushButton("← BACK")
        self.btn_back.setFixedSize(100, 36)
        self.btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {TEXT_MUTED};
                letter-spacing: 2px;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {CYAN}; }}
        """)
        self.btn_back.clicked.connect(self._on_back)
        back_row.addWidget(self.btn_back, alignment=Qt.AlignLeft)
        back_row.addStretch()
        root.addLayout(back_row)

        root.addStretch()

        # --- Card ---
        card = QFrame()
        card.setFixedWidth(700)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_SURFACE};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 20px;
            }}
        """)
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(60)
        sh.setColor(QColor(CYAN))
        sh.setOffset(0, 0)
        card.setGraphicsEffect(sh)

        cl = QVBoxLayout(card)
        cl.setSpacing(20)
        cl.setContentsMargins(40, 40, 40, 40)
        cl.setAlignment(Qt.AlignCenter)

        icon = CloudUploadIcon(size=80, color=CYAN)
        cl.addWidget(icon, alignment=Qt.AlignCenter)

        title = QLabel("GOOGLE CLOUD")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {CYAN};
            letter-spacing: 4px;
            border: none;
            background: transparent;
            font-family: 'Orbitron', 'JetBrains Mono', monospace;
            font-size: 24px;
            font-weight: 900;
        """)
        cl.addWidget(title)

        has_token = os.path.exists(_TOKEN_PATH)
        desc_text = (
            "Resuming your previous session…"
            if has_token
            else "Sign in with your Google account\nto run the pipeline on the cloud."
        )
        desc = QLabel(desc_text)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            border: none;
            background: transparent;
            font-size: 14px;
        """)
        cl.addWidget(desc)
        self._desc_lbl = desc

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {BORDER}; border: none;")
        cl.addWidget(divider)

        # Chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        chips_row.setAlignment(Qt.AlignCenter)
        for label, color in [("GPU Accelerated", NEON_GREEN), ("Scalable", CYAN), ("Secure", PURPLE)]:
            chip = QLabel(f"● {label}")
            chip.setStyleSheet(f"""
                color: {color};
                background: {color}22;
                border: 1px solid {color}55;
                border-radius: 12px;
                padding: 4px 12px;
                font-size: 12px;
            """)
            chips_row.addWidget(chip)
        cl.addLayout(chips_row)

        # Google sign-in button
        self.btn_google = QPushButton("  Sign in with Google")
        self.btn_google.setFixedSize(300, 54)
        self.btn_google.setCursor(Qt.PointingHandCursor)
        self.btn_google.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 27px;
                color: {TEXT_PRIMARY};
                font-family: 'JetBrains Mono', monospace;
                font-size: 14px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                border-color: {CYAN};
                background-color: {CYAN_GLOW};
                color: {CYAN};
            }}
            QPushButton:pressed {{ background-color: {CYAN}33; }}
            QPushButton:disabled {{
                border-color: {BORDER};
                color: {TEXT_MUTED};
            }}
        """)
        self.btn_google.clicked.connect(self._on_login)
        self.btn_google.setVisible(not has_token)
        cl.addWidget(self.btn_google, alignment=Qt.AlignCenter)

        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet(f"color: {TEXT_MUTED}; border: none; background: transparent; font-size: 13px;")
        cl.addWidget(self.status_lbl)

        root.addWidget(card, alignment=Qt.AlignCenter)
        root.addStretch()

        footer = QLabel("Your data is not stored locally  ·  OAuth 2.0 Secured")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        root.addWidget(footer)

    def _on_back(self):
        self._auto_triggered = False
        self.back_requested.emit()

    def _on_login(self):
        self.btn_google.setEnabled(False)
        self._set_status("Opening browser for authentication...", TEXT_SECONDARY)

        # Run auth in background thread — browser will open automatically
        self._thread = QThread()
        self._worker = AuthWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.success.connect(self._on_auth_success)
        self._worker.error.connect(self._on_auth_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

        # Animate status dots while waiting
        self._dot_tick = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_status)
        self._dot_timer.start(500)

    def _animate_status(self):
        self._dot_tick += 1
        dots = "." * ((self._dot_tick % 3) + 1)
        self._set_status(f"Waiting for browser authentication{dots}", TEXT_SECONDARY)

    def _on_auth_success(self, manager):
        self._dot_timer.stop()
        self.btn_google.setEnabled(True)
        self._set_status("✓ Authenticated successfully!", NEON_GREEN)
        QTimer.singleShot(800, lambda: self.login_success.emit(manager))

    def _on_auth_error(self, message: str):
        self._dot_timer.stop()
        self.btn_google.setEnabled(True)
        self._set_status(f"✗ {message}", NEON_ORANGE)

    def set_error(self, message: str):
        self._on_auth_error(message)

    def _set_status(self, text: str, color: str):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            f"color: {color}; border: none; background: transparent; font-size: 13px;"
        )
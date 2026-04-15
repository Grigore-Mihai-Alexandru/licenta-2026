# welcome_screen.py — First screen: choose Local or Google Cloud mode

import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QLinearGradient, QBrush

from ui.styles.theme import (
    BG_DEEP, BG_SURFACE, BG_ELEVATED,
    BORDER_BRIGHT, BORDER,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, PURPLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
)


class AnimatedBackground(QWidget):
    """Painted background: dark grid + pulsing cyan nodes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._tick = 0
        timer = QTimer(self)
        timer.timeout.connect(self._step)
        timer.start(50)

    def _step(self):
        self._tick += 1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background gradient
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(BG_DEEP))
        grad.setColorAt(1, QColor("#0A0F22"))
        p.fillRect(0, 0, w, h, grad)

        # Grid
        p.setPen(QPen(QColor(BORDER)))
        for x in range(0, w, 60):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 60):
            p.drawLine(0, y, w, y)

        # Pulsing nodes
        nodes = [
            (0.15, 0.2), (0.5, 0.1), (0.85, 0.25),
            (0.1, 0.7),  (0.9, 0.65), (0.5, 0.9),
            (0.3, 0.5),  (0.7, 0.45),
        ]
        prev = None
        for i, (rx, ry) in enumerate(nodes):
            t = self._tick * 0.05 + i * 1.2
            pulse = 0.5 + 0.5 * math.sin(t)
            nx, ny = int(rx * w), int(ry * h)
            r = int(4 + pulse * 4)
            c = QColor(CYAN)
            c.setAlpha(int(60 + pulse * 120))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(nx - r // 2, ny - r // 2, r, r)
            if prev:
                lc = QColor(CYAN)
                lc.setAlpha(20)
                p.setPen(QPen(lc, 1))
                p.drawLine(nx, ny, prev[0], prev[1])
            prev = (nx, ny)
        p.end()


class ModeCard(QPushButton):
    """Selectable card for Local / Remote mode."""

    def __init__(self, title: str, subtitle: str, icon: str, accent: str, parent=None):
        super().__init__(parent)
        self.accent = accent
        self.setFixedSize(350, 250)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 100))
        icon_lbl.setStyleSheet("background: transparent; border: none; font-size: 100px;")
        layout.addWidget(icon_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.title_lbl.setFont(QFont("JetBrains Mono", 17, QFont.Bold))
        self.title_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        layout.addWidget(self.title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setWordWrap(True)
        sub_lbl.setFont(QFont("JetBrains Mono", 12))
        sub_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent; border: none;")
        layout.addWidget(sub_lbl)

        self._set_style(False)

    def _set_style(self, hovered: bool):
        bg = BG_ELEVATED if hovered else BG_SURFACE
        border = self.accent if hovered else BORDER_BRIGHT
        bw = 2 if hovered else 1
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: {bw}px solid {border};
                border-radius: 16px;
            }}
        """)

    def enterEvent(self, e):
        self._set_style(True)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(40)
        sh.setColor(QColor(self.accent))
        sh.setOffset(0, 0)
        self.setGraphicsEffect(sh)
        self.title_lbl.setStyleSheet(f"color: {self.accent}; background: transparent; border: none;")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_style(False)
        self.setGraphicsEffect(None)
        self.title_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        super().leaveEvent(e)


class WelcomeScreen(QWidget):
    """
    Signals:
        local_selected  — user chose local execution
        remote_selected — user chose Google Cloud
    """
    local_selected  = Signal()
    remote_selected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        # Animated background layer
        self.bg = AnimatedBackground(self)
        self.bg.lower()

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)
        root.setSpacing(0)
        root.setContentsMargins(60, 40, 60, 60)

        # --- Header ---
        header = QVBoxLayout()
        header.setSpacing(8)
        header.setAlignment(Qt.AlignCenter)

        badge = QLabel("⬡  AI PIPELINE  ⬡")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFont(QFont("JetBrains Mono", 12))
        badge.setStyleSheet(f"""
            color: {CYAN};
            background: {CYAN_GLOW};
            border: 1px solid {CYAN_DIM};
            border-radius: 20px;
            padding: 8px 24px;
            letter-spacing: 3px;
        """)
        badge.setFixedWidth(300)
        header.addWidget(badge, alignment=Qt.AlignCenter)
        header.addSpacing(20)

        title = QLabel("NEURAL FORGE")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Orbitron", 48, QFont.Black))
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; letter-spacing: 6px;")
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(30)
        sh.setColor(QColor(CYAN))
        sh.setOffset(0, 0)
        title.setGraphicsEffect(sh)
        header.addWidget(title)

        subtitle = QLabel("Restormer  ·  Wonder3D  ·  Mesh Optimizer")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(QFont("JetBrains Mono", 15))
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; letter-spacing: 2px;")
        header.addWidget(subtitle)

        root.addLayout(header)
        root.addSpacing(60)

        # --- Mode label ---
        mode_lbl = QLabel("SELECT EXECUTION MODE")
        mode_lbl.setAlignment(Qt.AlignCenter)
        mode_lbl.setFont(QFont("JetBrains Mono", 13))
        mode_lbl.setStyleSheet(f"color: {TEXT_MUTED}; letter-spacing: 4px;")
        root.addWidget(mode_lbl)
        root.addSpacing(24)

        # --- Cards ---
        row = QHBoxLayout()
        row.setSpacing(32)
        row.setAlignment(Qt.AlignCenter)

        self.btn_local = ModeCard(
            title="LOCAL",
            subtitle="Run on your machine\nusing local GPU",
            icon="🖥️",
            accent=NEON_GREEN,
        )
        self.btn_local.clicked.connect(self.local_selected)
        row.addWidget(self.btn_local)

        sep = QLabel("OR")
        sep.setAlignment(Qt.AlignCenter)
        sep.setFont(QFont("JetBrains Mono", 14, QFont.Bold))
        sep.setStyleSheet(f"color: {TEXT_MUTED}; letter-spacing: 3px; font-size: 20px;")
        row.addWidget(sep)

        self.btn_remote = ModeCard(
            title="GOOGLE CLOUD",
            subtitle="Run remotely via\nGoogle Cloud Platform",
            icon="☁️",
            accent=CYAN,
        )
        self.btn_remote.clicked.connect(self.remote_selected)
        row.addWidget(self.btn_remote)

        root.addLayout(row)
        root.addSpacing(40)

        footer = QLabel("v1.0.0  ·  AI 3D Reconstruction Pipeline")
        footer.setAlignment(Qt.AlignCenter)
        footer.setFont(QFont("JetBrains Mono", 11))
        footer.setStyleSheet(f"color: {TEXT_MUTED};")
        root.addWidget(footer)

    def resizeEvent(self, event):
        self.bg.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

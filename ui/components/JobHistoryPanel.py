"""JobHistoryPanel - shows past pipeline jobs from ~/Downloads/NeuralForge/"""

import os
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from ui.styles.theme import (
    BG_DEEP, BG_SURFACE, BG_ELEVATED,
    BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)

_RESULT_EXTS = {".glb", ".obj", ".stl", ".json"}
_HISTORY_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "NeuralForge")


def _parse_job_date(folder_name: str) -> str:
    """Extract human-readable date from job folder name like 'image_2026-05-01_143022'."""
    parts = folder_name.rsplit("_", 2)
    if len(parts) >= 3:
        try:
            dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y-%m-%d_%H%M%S")
            return dt.strftime("%d %b %Y  %H:%M")
        except ValueError:
            pass
    return ""


def _scan_jobs() -> list[dict]:
    """Return list of {name, path, date_str, file_count, file_paths} dicts, newest first."""
    jobs = []
    if not os.path.isdir(_HISTORY_DIR):
        return jobs

    for name in sorted(os.listdir(_HISTORY_DIR), reverse=True):
        path = os.path.join(_HISTORY_DIR, name)
        if not os.path.isdir(path):
            continue
        file_paths = []
        for root, _, files in os.walk(path):
            for f in files:
                if os.path.splitext(f)[1].lower() in _RESULT_EXTS:
                    file_paths.append(os.path.join(root, f))
        jobs.append({
            "name":       name,
            "path":       path,
            "date_str":   _parse_job_date(name),
            "file_count": len(file_paths),
            "file_paths": file_paths,
        })
    return jobs


class _JobCard(QFrame):
    load_clicked = Signal(list)

    def __init__(self, job: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 10px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        # Left: job info
        info_col = QVBoxLayout()
        info_col.setSpacing(3)

        # Job name (strip timestamp suffix for display)
        display_name = job["name"]
        parts = display_name.rsplit("_", 2)
        if len(parts) == 3:
            display_name = parts[0]

        name_lbl = QLabel(display_name)
        name_lbl.setFont(QFont("JetBrains Mono", 15, QFont.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent; border: none;")
        info_col.addWidget(name_lbl)

        if job["date_str"]:
            date_lbl = QLabel(job["date_str"])
            date_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 15px; background: transparent; border: none;")
            info_col.addWidget(date_lbl)

        # File count badge
        n = job["file_count"]
        color = NEON_GREEN if n > 0 else NEON_ORANGE
        badge_text = f"{n} file{'s' if n != 1 else ''}" if n > 0 else "empty"
        badge = QLabel(badge_text)
        badge.setStyleSheet(f"""
            color: {color}; background: {color}18;
            border: 1px solid {color}55; border-radius: 8px;
            padding: 2px 8px; font-size: 15px;
        """)
        info_col.addWidget(badge, alignment=Qt.AlignLeft)

        row.addLayout(info_col, 1)

        # Right: Load button (only if files exist)
        if job["file_paths"]:
            btn = QPushButton("Load")
            btn.setFixedSize(96, 32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {CYAN}18; border: 1px solid {CYAN}88;
                    border-radius: 6px; color: {CYAN};
                    font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{ background: {CYAN}33; border-color: {CYAN}; }}
                QPushButton:pressed {{ background: {CYAN}44; }}
            """)
            btn.clicked.connect(lambda: self.load_clicked.emit(job["file_paths"]))
            row.addWidget(btn, alignment=Qt.AlignVCenter)

    def enterEvent(self, event):
        self.setStyleSheet(f"""
            QFrame {{
                background: {BG_ELEVATED};
                border: 1px solid {CYAN}66;
                border-radius: 10px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(f"""
            QFrame {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 10px;
            }}
        """)
        super().leaveEvent(event)


class JobHistoryPanel(QDialog):
    """
    Frameless side panel listing past pipeline jobs.
    Emits load_requested(paths) when the user clicks Load on a job.
    """
    load_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(False)
        self.setFixedWidth(420)
        self._build()

        # Position: right edge of parent, full height
        if parent:
            pg = parent.geometry()
            self.setFixedHeight(pg.height() - 60)
            self.move(pg.right() - self.width() - 8, pg.top() + 55)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("hist_container")
        container.setStyleSheet(f"""
            QFrame#hist_container {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 14px;
            }}
        """)
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(40)
        sh.setColor(QColor(CYAN))
        sh.setOffset(-4, 0)
        container.setGraphicsEffect(sh)
        outer.addWidget(container)

        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(16, 16, 16, 16)
        vlay.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("JOB HISTORY")
        title.setFont(QFont("JetBrains Mono", 16, QFont.Bold))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 3px;")
        header_row.addWidget(title)
        header_row.addStretch()

        btn_close = QPushButton("X")
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {BORDER_BRIGHT};
                border-radius: 14px; color: {TEXT_MUTED}; font-size: 15px;
            }}
            QPushButton:hover {{ border-color: {NEON_ORANGE}; color: {NEON_ORANGE}; }}
        """)
        btn_close.clicked.connect(self.close)
        header_row.addWidget(btn_close)
        vlay.addLayout(header_row)

        hint = QLabel(f"Jobs saved to  ~/Downloads/NeuralForge/")
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 15px;")
        vlay.addWidget(hint)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {BORDER}; border: none;")
        vlay.addWidget(divider)

        # Scrollable job list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {BG_ELEVATED}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_BRIGHT}; border-radius: 3px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {CYAN}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        jobs = _scan_jobs()
        if jobs:
            for job in jobs:
                card = _JobCard(job)
                card.load_clicked.connect(self._on_load)
                list_layout.addWidget(card)
        else:
            empty = QLabel("No past jobs found.\nRun a pipeline to see history here.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 15px;")
            list_layout.addWidget(empty)

        list_layout.addStretch()
        scroll.setWidget(list_widget)
        vlay.addWidget(scroll, 1)

        # Footer
        count_lbl = QLabel(
            f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} found"
            if jobs else "History directory not found"
        )
        count_lbl.setAlignment(Qt.AlignCenter)
        count_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 15px;")
        vlay.addWidget(count_lbl)

    def _on_load(self, paths: list):
        self.load_requested.emit(paths)
        self.close()

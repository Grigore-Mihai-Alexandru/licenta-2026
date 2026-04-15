# pipeline_screen.py — Main 3-column pipeline screen

import os
import sys
import urllib.request
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QTextEdit, QFrame, QSlider, QSizePolicy,
    QComboBox, QCheckBox, QSpinBox, QDialog, QScrollArea,
    QGraphicsDropShadowEffect
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtCore import Qt, QUrl, QTimer, Signal, QThread, QObject
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont

from ui.styles.theme import (
    BG_BASE, BG_SURFACE, BG_ELEVATED, BG_DEEP,
    BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE, PURPLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
)

IDLE    = "idle"
RUNNING = "running"
DONE    = "done"
ERROR   = "error"

VERTEX_DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                      "JOB_STATE_CANCELLED", "JOB_STATE_PAUSED"}

RESTORMER_TASKS = [
    "Real_Denoising",
    "Motion_Deblurring",
    "Single_Image_Defocus_Deblurring",
    "Deraining",
    "Gaussian_Color_Denoising",
    "Gaussian_Gray_Denoising",
]

COMBO_STYLE = f"""
    QComboBox {{
        background: {BG_ELEVATED};
        border: 1px solid {BORDER_BRIGHT};
        border-radius: 6px;
        color: {TEXT_PRIMARY};
        padding: 6px 10px;
        font-size: 12px;
        font-family: 'JetBrains Mono', monospace;
    }}
    QComboBox:hover {{ border-color: {CYAN}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_BRIGHT};
        selection-background-color: {CYAN_GLOW};
        selection-color: {CYAN};
    }}
"""


# -- Helpers -------------------------------------------------------------------

def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {TEXT_MUTED};
        font-size: 10px;
        font-family: 'JetBrains Mono', monospace;
        letter-spacing: 3px;
        font-weight: bold;
        padding-bottom: 2px;
        border-bottom: 1px solid {BORDER};
    """)
    return lbl


def card(min_height: int = 0) -> QFrame:
    f = QFrame()
    if min_height:
        f.setMinimumHeight(min_height)
    f.setStyleSheet(f"""
        QFrame {{
            background-color: {BG_SURFACE};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
    """)
    return f


# -- Restormer multi-select popup ----------------------------------------------

class TaskPickerDialog(QDialog):
    """Floating checklist for Restormer task selection."""

    def __init__(self, selected: list[str], parent=None):
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

        self.checkboxes: dict[str, QCheckBox] = {}
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

        # Confirm button
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

    def selected_tasks(self) -> list[str]:
        return [t for t, cb in self.checkboxes.items() if cb.isChecked()]


class TaskPickerButton(QWidget):
    """Button that shows selected tasks summary + opens TaskPickerDialog."""

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
            self.btn.setText("None selected  ▾")
        elif len(self._selected) == 1:
            self.btn.setText(f"{self._selected[0]}  ▾")
        else:
            self.btn.setText(f"{len(self._selected)} tasks selected  ▾")

    def _open_picker(self):
        dlg = TaskPickerDialog(self._selected, parent=self)
        # Position below the button
        pos = self.btn.mapToGlobal(self.btn.rect().bottomLeft())
        dlg.move(pos)
        if dlg.exec():
            result = dlg.selected_tasks()
            if result:  # don't allow zero selection
                self._selected = result
            self._refresh_label()

    def selected_tasks(self) -> list[str]:
        return list(self._selected)


# -- Labeled slider with editable spinbox -------------------------------------

class LabeledSlider(QWidget):
    """
    Slider + editable SpinBox on the right.
    For snap_values: slider snaps to those discrete values only.
    """

    def __init__(self, label: str, min_val: int, max_val: int,
                 default: int, step: int = 1,
                 snap_values: list[int] = None, parent=None):
        super().__init__(parent)
        self._snap = snap_values  # if set, slider maps index → value

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        top.addWidget(lbl)
        top.addStretch()

        # Editable spinbox instead of plain label
        self.spinbox = QSpinBox()
        self.spinbox.setRange(min_val, max_val)
        self.spinbox.setValue(default)
        self.spinbox.setFixedWidth(72)
        self.spinbox.setAlignment(Qt.AlignRight)
        self.spinbox.setButtonSymbols(QSpinBox.NoButtons)
        self.spinbox.setStyleSheet(f"""
            QSpinBox {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 4px;
                color: {CYAN};
                font-size: 11px;
                font-weight: bold;
                font-family: 'JetBrains Mono', monospace;
                padding: 1px 4px;
            }}
            QSpinBox:focus {{ border-color: {CYAN}; }}
        """)
        top.addWidget(self.spinbox)
        layout.addLayout(top)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {BORDER_BRIGHT}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {CYAN}; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {CYAN_DIM}; border-radius: 2px;
            }}
        """)

        if snap_values:
            self.slider.setRange(0, len(snap_values) - 1)
            # Set slider to index of default (or nearest)
            idx = min(range(len(snap_values)), key=lambda i: abs(snap_values[i] - default))
            self.slider.setValue(idx)
            self.spinbox.setRange(snap_values[0], snap_values[-1])
            self.spinbox.setValue(snap_values[idx])

            self.slider.valueChanged.connect(self._snap_slider_changed)
            self.spinbox.editingFinished.connect(self._spinbox_edited_snap)
        else:
            self.slider.setRange(min_val, max_val)
            self.slider.setValue(default)
            self.slider.setSingleStep(step)
            self.slider.valueChanged.connect(
                lambda v: self.spinbox.setValue(v)
            )
            self.spinbox.editingFinished.connect(self._spinbox_edited)

        layout.addWidget(self.slider)

    def _snap_slider_changed(self, idx: int):
        v = self._snap[idx]
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(v)
        self.spinbox.blockSignals(False)

    def _spinbox_edited_snap(self):
        # Snap to nearest valid value
        typed = self.spinbox.value()
        idx   = min(range(len(self._snap)), key=lambda i: abs(self._snap[i] - typed))
        self.spinbox.setValue(self._snap[idx])
        self.slider.blockSignals(True)
        self.slider.setValue(idx)
        self.slider.blockSignals(False)

    def _spinbox_edited(self):
        v = self.spinbox.value()
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)

    def value(self) -> int:
        return self.spinbox.value()


# -- Drive worker --------------------------------------------------------------

class DriveWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, creds, file_paths: list[str], output_dir: str):
        super().__init__()
        self.creds      = creds
        self.file_paths = file_paths
        self.output_dir = output_dir

    def run(self):
        try:
            cloud_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "cloud")
            )
            if cloud_dir not in sys.path:
                sys.path.insert(0, cloud_dir)
            from DriveManager import DriveManager
            dm = DriveManager(self.creds)
            downloaded = dm.save_and_download(
                self.file_paths, self.output_dir,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(downloaded)
        except Exception as e:
            self.error.emit(str(e))


# -- Step widget ---------------------------------------------------------------

class StepWidget(QWidget):
    def __init__(self, number: int, name: str, subtitle: str, icon: str, parent=None):
        super().__init__(parent)
        self.number = number
        self._state = IDLE
        self._icon  = icon

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
            font-size: 13px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace;
            color: {TEXT_PRIMARY};
        """)
        text_col.addWidget(self.name_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
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
            circle_bg, circle_color = BG_ELEVATED, TEXT_MUTED
            badge_text, badge_color = "IDLE", TEXT_MUTED
            circle_content = str(self.number)
        elif s == RUNNING:
            circle_bg, circle_color = CYAN_GLOW, CYAN
            badge_text, badge_color = "RUNNING", CYAN
            circle_content = self._icon
        elif s == DONE:
            circle_bg, circle_color = f"{NEON_GREEN}22", NEON_GREEN
            badge_text, badge_color = "DONE", NEON_GREEN
            circle_content = "OK"
        else:
            circle_bg, circle_color = f"{NEON_ORANGE}22", NEON_ORANGE
            badge_text, badge_color = "ERROR", NEON_ORANGE
            circle_content = "X"

        self.circle.setText(circle_content)
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
            font-size: 10px; font-weight: bold;
            letter-spacing: 1px; padding: 3px 6px;
        """)
        name_color = TEXT_PRIMARY if s != IDLE else TEXT_SECONDARY
        self.name_lbl.setStyleSheet(f"""
            font-size: 13px; font-weight: bold;
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


# -- Top bar -------------------------------------------------------------------

class TopBar(QWidget):
    def __init__(self, run_mode: str, user_info: dict = None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            background-color: {BG_SURFACE};
            border-bottom: 1px solid {BORDER};
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        logo = QLabel("⬡ NEURAL FORGE")
        logo.setStyleSheet(f"""
            color: {CYAN}; font-size: 14px; font-weight: bold;
            font-family: 'JetBrains Mono', monospace; letter-spacing: 2px;
        """)
        layout.addWidget(logo)
        layout.addStretch()

        mode_color = NEON_GREEN if run_mode == "local" else CYAN
        mode_text  = "● LOCAL" if run_mode == "local" else "● CLOUD"
        mode_badge = QLabel(mode_text)
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
                px = px.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                rounded = QPixmap(32, 32)
                rounded.fill(Qt.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.Antialiasing)
                from PySide6.QtGui import QPainterPath
                path = QPainterPath()
                path.addEllipse(0, 0, 32, 32)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, px)
                painter.end()
                self.avatar.setPixmap(rounded)
                self.avatar.setStyleSheet("border-radius: 16px;")
        except Exception:
            pass


# -- Main pipeline screen ------------------------------------------------------

class PipelineScreen(QWidget):
    logout_requested = Signal()

    def __init__(self, run_mode: str = "local", credentials=None,
                 user_info: dict = None, parent=None):
        super().__init__(parent)
        self.run_mode    = run_mode
        self.credentials = credentials
        self.user_info   = user_info or {}
        self.image_path  = None
        self.base_dir    = os.path.dirname(os.path.abspath(__file__))

        self._vertex_job   = None
        self._poll_timer   = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_vertex_job)

        self._drive_thread = None
        self._drive_worker = None
        self._result_paths: list[str] = []

        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = TopBar(self.run_mode, self.user_info)
        root.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(12)
        root.addLayout(body)

        body.addLayout(self._build_left(), 2)
        body.addLayout(self._build_center(), 2)
        body.addWidget(self._build_right(), 4)

    # -- LEFT -----------------------------------------------------------------

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        col.addWidget(section_label("INPUT IMAGE"))
        col.addSpacing(4)

        img_card   = card()
        img_layout = QVBoxLayout(img_card)
        img_layout.setContentsMargins(14, 14, 14, 14)
        img_layout.setSpacing(10)

        self.img_preview = QLabel("No image loaded")
        self.img_preview.setAlignment(Qt.AlignCenter)
        self.img_preview.setFixedHeight(200)
        self.img_preview.setStyleSheet(f"""
            background: {BG_ELEVATED};
            border: 2px dashed {BORDER_BRIGHT};
            border-radius: 8px;
            color: {TEXT_MUTED}; font-size: 12px;
        """)
        img_layout.addWidget(self.img_preview)

        self.img_name_lbl = QLabel("")
        self.img_name_lbl.setAlignment(Qt.AlignCenter)
        self.img_name_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        img_layout.addWidget(self.img_name_lbl)

        self.btn_load = QPushButton("Load Image")
        self.btn_load.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {BORDER_BRIGHT}; border-radius: 8px;
                padding: 8px; font-size: 12px; color: {TEXT_PRIMARY};
            }}
            QPushButton:hover {{ border-color: {CYAN}; color: {CYAN}; background: {CYAN_GLOW}; }}
        """)
        self.btn_load.clicked.connect(self._load_image)
        img_layout.addWidget(self.btn_load)

        col.addWidget(img_card)
        col.addSpacing(8)

        col.addWidget(section_label("SETTINGS"))
        col.addSpacing(4)

        settings_card = card()
        slay = QVBoxLayout(settings_card)
        slay.setContentsMargins(16, 16, 16, 16)
        slay.setSpacing(12)

        # Restormer — multi-select popup button
        task_lbl = QLabel("Restormer Tasks")
        task_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        slay.addWidget(task_lbl)

        self.task_picker = TaskPickerButton()
        slay.addWidget(self.task_picker)

        # Wonder3D mode
        wonder_lbl = QLabel("Wonder3D Mode")
        wonder_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        slay.addWidget(wonder_lbl)

        self.combo_wonder3d = QComboBox()
        self.combo_wonder3d.addItems([
            "float32  (high VRAM usage)",
            "float16  (lower VRAM usage)",
        ])
        self.combo_wonder3d.setCurrentIndex(0 if self.run_mode == "remote" else 1)
        self.combo_wonder3d.setStyleSheet(COMBO_STYLE)
        slay.addWidget(self.combo_wonder3d)

        # Crop size — snap to nice multiples of 32 starting at 96
        crop_snaps = [96, 128, 160, 192, 224, 256, 320, 384, 512]
        self.slider_crop   = LabeledSlider(
            "Crop Size", 96, 512, 160, snap_values=crop_snaps
        )
        # Refine steps
        self.slider_refine = LabeledSlider("Refine Steps",  0,   50,     0, step=1)
        # Target faces — steps of 1000
        self.slider_faces  = LabeledSlider("Target Faces", 1000, 50000, 8000, step=1000)
        # LOD stages
        self.slider_stages = LabeledSlider("LOD Stages",   1,    5,     1, step=1)

        slay.addWidget(self.slider_crop)
        slay.addWidget(self.slider_refine)
        slay.addWidget(self.slider_faces)
        slay.addWidget(self.slider_stages)

        # 3D Print mode
        self.check_print = QCheckBox("3D Print mode  (watertight + STL export)")
        self.check_print.setStyleSheet(f"""
            QCheckBox {{
                color: {TEXT_SECONDARY};
                font-size: 11px;
                font-family: 'JetBrains Mono', monospace;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 3px;
                background: {BG_ELEVATED};
            }}
            QCheckBox::indicator:checked {{
                background: {CYAN}; border-color: {CYAN};
            }}
        """)
        slay.addWidget(self.check_print)

        col.addWidget(settings_card)
        col.addStretch()

        self.btn_run = QPushButton("▶  START PIPELINE")
        self.btn_run.setFixedHeight(48)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{
                background: {NEON_GREEN}22; border: 2px solid {NEON_GREEN};
                border-radius: 10px; color: {NEON_GREEN};
                font-size: 13px; font-weight: bold; letter-spacing: 2px;
            }}
            QPushButton:hover {{ background: {NEON_GREEN}44; }}
            QPushButton:disabled {{ border-color: {BORDER}; color: {TEXT_MUTED}; background: transparent; }}
        """)
        self.btn_run.clicked.connect(self._start_pipeline)
        col.addWidget(self.btn_run)

        return col

    # -- CENTER ----------------------------------------------------------------

    def _build_center(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        col.addWidget(section_label("PIPELINE STEPS"))
        col.addSpacing(4)

        steps_card   = card()
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(8, 12, 8, 12)
        steps_layout.setSpacing(0)

        self.step_widgets = []
        steps_data = [
            (1, "RESTORMER", "Image denoising",     "🔬"),
            (2, "WONDER3D",  "3D model generation", "🌐"),
            (3, "MESH OPT",  "LOD generation",      "⬡"),
        ]
        for i, (num, name, sub, icon) in enumerate(steps_data):
            sw = StepWidget(num, name, sub, icon)
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

        self.btn_save = QPushButton("☁  Save & Download via Drive")
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
        self.btn_save.clicked.connect(self._save_to_drive)
        status_lay.addWidget(self.btn_save)

        col.addWidget(status_card)
        col.addSpacing(8)

        col.addWidget(section_label("LOG OUTPUT"))
        col.addSpacing(4)

        log_card = card()
        log_lay  = QVBoxLayout(log_card)
        log_lay.setContentsMargins(0, 0, 0, 0)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Pipeline logs will appear here...")
        self.log.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; border: none;
                border-radius: 12px; color: {TEXT_SECONDARY};
                font-size: 11px; padding: 12px;
            }}
        """)
        log_lay.addWidget(self.log)
        col.addWidget(log_card, 1)

        return col

    # -- RIGHT -----------------------------------------------------------------

    def _build_right(self) -> QWidget:
        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(section_label("3D VIEWER"))
        layout.addSpacing(4)

        viewer_frame = card()
        viewer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vlay = QVBoxLayout(viewer_frame)
        vlay.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView()
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        viewer_path = os.path.join(self.base_dir, "viewer", "index.html")
        if os.path.exists(viewer_path):
            self.web_view.setUrl(QUrl.fromLocalFile(viewer_path))
        else:
            self.web_view.setHtml(self._viewer_placeholder())

        vlay.addWidget(self.web_view)
        layout.addWidget(viewer_frame, 1)

        return container

    def _viewer_placeholder(self) -> str:
        return f"""<html><body style="background:{BG_DEEP};display:flex;align-items:center;
        justify-content:center;height:100vh;margin:0;font-family:monospace;">
        <div style="text-align:center;color:{TEXT_MUTED};">
            <div style="font-size:48px;margin-bottom:16px;">⬡</div>
            <div style="color:{TEXT_SECONDARY};font-size:14px;">3D Viewer</div>
            <div style="font-size:12px;margin-top:8px;">viewer/index.html not found</div>
        </div></body></html>"""

    # -- Actions ---------------------------------------------------------------

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return
        self.image_path = path
        self.img_name_lbl.setText(os.path.basename(path))
        px = QPixmap(path)
        if not px.isNull():
            px = px.scaled(
                self.img_preview.width() - 8,
                self.img_preview.height() - 8,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.img_preview.setPixmap(px)
            self.img_preview.setStyleSheet(f"""
                background: {BG_ELEVATED};
                border: 2px solid {CYAN_DIM};
                border-radius: 8px;
            """)
        self._log(f"[INPUT] Loaded: {os.path.basename(path)}")

    def _start_pipeline(self):
        if not self.image_path:
            self._log("[ERROR] No image selected.", NEON_ORANGE)
            return

        tasks          = self.task_picker.selected_tasks()
        restormer_tasks = ",".join(tasks)
        wonder3d_mode  = "float16" if self.combo_wonder3d.currentIndex() == 1 else "official"
        crop           = self.slider_crop.value()
        refine         = self.slider_refine.value()
        faces          = self.slider_faces.value()
        stages         = self.slider_stages.value()
        print_mode     = self.check_print.isChecked()

        self._log(
            f"[CONFIG] tasks={restormer_tasks}, wonder3d={wonder3d_mode}, "
            f"crop={crop}, refine={refine}, faces={faces}, stages={stages}, "
            f"print={print_mode}"
        )

        self.btn_run.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.btn_save.setVisible(False)
        self._result_paths = []

        for sw in self.step_widgets:
            sw.set_state(IDLE)

        if self.run_mode == "local":
            self._run_local_simulate()
        else:
            self._run_cloud(restormer_tasks, wonder3d_mode, crop, refine, faces, stages, print_mode)

    # -- Local simulate --------------------------------------------------------

    def _run_local_simulate(self):
        self._simulate_step(0)

    def _simulate_step(self, index: int):
        if index >= len(self.step_widgets):
            self._on_pipeline_done(success=True)
            return
        names = ["Restormer denoising", "Wonder3D generation", "Mesh LOD generation"]
        self.step_widgets[index].set_state(RUNNING)
        self._log(f"[STEP {index+1}] {names[index]}...")
        QTimer.singleShot(2000, lambda: self._finish_step(index))

    def _finish_step(self, index: int):
        self.step_widgets[index].set_state(DONE)
        self._log(f"[STEP {index+1}] Done ")
        self._simulate_step(index + 1)

    # -- Cloud -----------------------------------------------------------------

    def _run_cloud(self, restormer_tasks, wonder3d_mode, crop, refine, faces, stages, print_mode):
        try:
            cloud_dir = os.path.abspath(os.path.join(self.base_dir, "..", "cloud"))
            if cloud_dir not in sys.path:
                sys.path.insert(0, cloud_dir)

            manager   = self.credentials
            cloud_uri = manager.upload_file(self.image_path)
            image_uri = manager.setup_artifact_registry()

            self._vertex_job = manager.launch_vertex_job(
                image_uri=image_uri,
                input_uri=cloud_uri,
                crop_size=crop,
                refine=refine,
                mesh_faces=faces,
                mesh_stages=stages,
                wonder3d_mode=wonder3d_mode,
                restormer_tasks=restormer_tasks,
            )

            job_name = self._vertex_job.resource_name.split("/")[-1]
            self._log(f"[CLOUD] Job submitted: {job_name}")
            self._set_job_status("Submitted — waiting for GPU...", CYAN)
            self.job_id_lbl.setText(self._vertex_job.resource_name)

            for sw in self.step_widgets:
                sw.set_state(RUNNING)

            self._poll_timer.start(30_000)

        except Exception as e:
            self._log(f"[ERROR] {e}", NEON_ORANGE)
            self._on_pipeline_done(success=False)

    def _poll_vertex_job(self):
        if not self._vertex_job:
            self._poll_timer.stop()
            return
        try:
            self._vertex_job.refresh()
            state = self._vertex_job.state.name
            self._log(f"[POLL] Job state: {state}")
            self._set_job_status(f"Job: {state}", CYAN)

            if state == "JOB_STATE_SUCCEEDED":
                self._poll_timer.stop()
                for sw in self.step_widgets:
                    sw.set_state(DONE)
                self._log("[CLOUD]  Job succeeded!", NEON_GREEN)
                self._on_pipeline_done(success=True)
            elif state in VERTEX_DONE_STATES:
                self._poll_timer.stop()
                for sw in self.step_widgets:
                    sw.set_state(ERROR)
                self._log(f"[CLOUD] Job ended: {state}", NEON_ORANGE)
                self._on_pipeline_done(success=False)

        except Exception as e:
            self._log(f"[POLL ERROR] {e}", NEON_ORANGE)

    def _set_job_status(self, text: str, color: str):
        self.job_status_lbl.setText(text)
        self.job_status_lbl.setStyleSheet(f"""
            color: {color}; font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
        """)

    # -- Pipeline done ---------------------------------------------------------

    def _on_pipeline_done(self, success: bool):
        self.btn_run.setEnabled(True)
        self.btn_load.setEnabled(True)

        if success:
            self._log("[PIPELINE]  Complete!", NEON_GREEN)
            self._set_job_status("Completed ", NEON_GREEN)

            outputs_dir = os.path.join(self.base_dir, "..", "outputs")
            if os.path.isdir(outputs_dir):
                exts = {".glb", ".obj", ".stl", ".json"}
                self._result_paths = [
                    os.path.join(outputs_dir, f)
                    for f in os.listdir(outputs_dir)
                    if os.path.splitext(f)[1].lower() in exts
                ]
                self._log(f"[OUTPUT] Found {len(self._result_paths)} result file(s).")

            if self.run_mode == "remote" and self._result_paths:
                self.btn_save.setVisible(True)
        else:
            self._log("[PIPELINE] Failed.", NEON_ORANGE)
            self._set_job_status("Failed X", NEON_ORANGE)

    # -- Drive -----------------------------------------------------------------

    def _save_to_drive(self):
        if not self._result_paths:
            self._log("[DRIVE] No result files to upload.", NEON_ORANGE)
            return

        local_dl_dir = os.path.join(os.path.expanduser("~"), "Downloads", "NeuralForge")
        creds = self.credentials.creds if hasattr(self.credentials, "creds") else self.credentials

        self.btn_save.setEnabled(False)
        self._log(f"[DRIVE] Uploading {len(self._result_paths)} file(s)...")

        self._drive_thread = QThread()
        self._drive_worker = DriveWorker(creds, self._result_paths, local_dl_dir)
        self._drive_worker.moveToThread(self._drive_thread)

        self._drive_thread.started.connect(self._drive_worker.run)
        self._drive_worker.progress.connect(self._on_drive_progress)
        self._drive_worker.finished.connect(self._on_drive_done)
        self._drive_worker.error.connect(self._on_drive_error)
        self._drive_worker.finished.connect(self._drive_thread.quit)
        self._drive_worker.error.connect(self._drive_thread.quit)

        self._drive_thread.start()

    def _on_drive_progress(self, filename: str, pct: int):
        self._log(f"[DRIVE] {filename} — {pct}%")

    def _on_drive_done(self, downloaded: list[str]):
        self.btn_save.setEnabled(True)
        dl_dir = os.path.dirname(downloaded[0]) if downloaded else ""
        self._log(f"[DRIVE]  {len(downloaded)} file(s) → {dl_dir}", NEON_GREEN)
        self._set_job_status("Saved to Drive + Downloaded ", NEON_GREEN)

    def _on_drive_error(self, message: str):
        self.btn_save.setEnabled(True)
        self._log(f"[DRIVE ERROR] {message}", NEON_ORANGE)

    # -- Public API ------------------------------------------------------------

    def set_step_state(self, step_index: int, state: str):
        if 0 <= step_index < len(self.step_widgets):
            self.step_widgets[step_index].set_state(state)

    def load_3d_model(self, obj_path: str):
        self.web_view.page().runJavaScript(f"window.loadModel('{obj_path}')")
        self._log(f"[VIEWER] Loaded: {os.path.basename(obj_path)}")

    def _log(self, message: str, color: str = None):
        if color:
            self.log.append(f'<span style="color:{color}">{message}</span>')
        else:
            self.log.append(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QCheckBox, QProgressBar,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent


class DropImageLabel(QLabel):
    """Image preview label that also accepts drag-and-drop of image files."""
    file_dropped = Signal(str)

    _ACCEPT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self._default_style = ""

    def _is_image_url(self, url) -> bool:
        return os.path.splitext(url.toLocalFile())[1].lower() in self._ACCEPT_EXTS

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            if any(self._is_image_url(u) for u in event.mimeData().urls()):
                event.acceptProposedAction()
                self.setStyleSheet(self.styleSheet().replace(
                    "border: 2px dashed", "border: 2px solid"
                ))
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.styleSheet().replace(
            "border: 2px solid", "border: 2px dashed"
        ))

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.styleSheet().replace(
            "border: 2px solid", "border: 2px dashed"
        ))
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.splitext(path)[1].lower() in self._ACCEPT_EXTS:
                self.file_dropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()


from ui.styles.theme import (
    BG_BASE, BG_ELEVATED, BG_SURFACE, BORDER, BORDER_BRIGHT,
    CYAN, CYAN_GLOW, CYAN_DIM,
    NEON_GREEN, NEON_ORANGE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)
from ui.components.pipeline.constants import COMBO_STYLE
from ui.components.pipeline.helpers import section_label, card
from ui.components.pipeline.sliders import LabeledSlider
from ui.components.pipeline.task_picker import TaskPickerButton


class LeftPanel(QWidget):
    image_loaded  = Signal(str)
    run_requested = Signal()

    def __init__(self, run_mode: str = "local", parent=None):
        super().__init__(parent)
        self._image_path = None
        self._run_mode   = run_mode
        self._build()

    @property
    def image_path(self) -> str:
        return self._image_path

    def get_settings(self) -> dict:
        tasks = self.task_picker.selected_tasks()
        # Gaussian_Gray_Denoising outputs a grayscale image, which breaks Wonder3D.
        # Move it to the front so color tasks always run last and produce RGB output.
        _GRAY = {"Gaussian_Gray_Denoising"}
        tasks = [t for t in tasks if t in _GRAY] + [t for t in tasks if t not in _GRAY]
        return {
            "restormer_tasks": ",".join(tasks),
            "wonder3d_mode":   "float16" if self.combo_wonder3d.currentIndex() == 1 else "official",
            "crop":            self.slider_crop.value(),
            "refine":          self.slider_refine.value(),
            "mesh_optimize":   self.check_mesh_opt.isChecked(),
            "faces":           self.slider_faces.value(),
            "stages":          self.slider_stages.value(),
            "print_mode":      self.check_print.isChecked(),
        }

    def set_controls_enabled(self, enabled: bool):
        self.btn_run.setEnabled(enabled)
        self.btn_load.setEnabled(enabled)

    def set_budget(self, spent: float, limit: float, jobs: int = 0):
        if not hasattr(self, "_budget_widget"):
            return
        pct = min(int((spent / limit) * 100), 100) if limit > 0 else 0
        self._budget_lbl.setText(
            f"Budget  ${spent:.2f} / ${limit:.2f}   ({pct}%  ·  {jobs} job{'s' if jobs != 1 else ''})"
        )
        self._budget_bar.setValue(pct)
        color = NEON_GREEN if pct < 60 else (NEON_ORANGE if pct < 85 else "#FF4444")
        self._budget_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {BG_ELEVATED}; border: 1px solid {BORDER_BRIGHT};
                border-radius: 4px; height: 8px;
            }}
            QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}
        """)
        self._budget_widget.setVisible(True)

    def _checkbox_style(self) -> str:
        return f"""
            QCheckBox {{
                color: {TEXT_SECONDARY};
                font-size: 15px;
                font-family: 'JetBrains Mono', monospace;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px; height: 18px;
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 4px;
                background: {BG_ELEVATED};
            }}
            QCheckBox::indicator:checked {{
                background: {CYAN}; border-color: {CYAN};
            }}
        """

    def _on_drop(self, path: str):
        self._set_image(path)

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return
        self._set_image(path)

    def _set_image(self, path: str):
        self._image_path = path
        self.img_name_lbl.setText(os.path.basename(path))
        px = QPixmap(path)
        if not px.isNull():
            px = px.scaled(
                self.img_preview.width() - 8,
                self.img_preview.height() - 8,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.img_preview.setPixmap(px)
            self.img_preview.setStyleSheet(f"""
                background: {BG_ELEVATED};
                border: 2px solid {CYAN_DIM};
                border-radius: 8px;
            """)
        self.image_loaded.emit(path)

    def _build(self):
        # Outer layout: scroll area on top, run button pinned at bottom
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Scrollable area
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

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(10)

        # INPUT IMAGE
        col.addWidget(section_label("INPUT IMAGE"))
        col.addSpacing(4)

        img_card   = card()
        img_layout = QVBoxLayout(img_card)
        img_layout.setContentsMargins(14, 14, 14, 14)
        img_layout.setSpacing(10)

        self.img_preview = DropImageLabel("Drop image here\nor click Load")
        self.img_preview.setAlignment(Qt.AlignCenter)
        self.img_preview.setFixedHeight(200)
        self.img_preview.setStyleSheet(f"""
            background: {BG_ELEVATED};
            border: 2px dashed {BORDER_BRIGHT};
            border-radius: 8px;
            color: {TEXT_MUTED}; font-size: 15px;
        """)
        self.img_preview.file_dropped.connect(self._on_drop)
        img_layout.addWidget(self.img_preview)

        self.img_name_lbl = QLabel("")
        self.img_name_lbl.setAlignment(Qt.AlignCenter)
        self.img_name_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
        img_layout.addWidget(self.img_name_lbl)

        self.btn_load = QPushButton("Load Image")
        self.btn_load.setFixedHeight(40)
        self.btn_load.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {BORDER_BRIGHT}; border-radius: 8px;
                padding: 8px; font-size: 15px; color: {TEXT_PRIMARY};
            }}
            QPushButton:hover {{ border-color: {CYAN}; color: {CYAN}; background: {CYAN_GLOW}; }}
        """)
        self.btn_load.clicked.connect(self._load_image)
        img_layout.addWidget(self.btn_load)

        col.addWidget(img_card)
        col.addSpacing(8)

        # SETTINGS
        col.addWidget(section_label("SETTINGS"))
        col.addSpacing(4)

        settings_card = card()
        slay = QVBoxLayout(settings_card)
        slay.setContentsMargins(18, 18, 18, 18)
        slay.setSpacing(16)

        task_lbl = QLabel("Restormer Tasks")
        task_lbl.setStyleSheet(f"font-size: 15px; color: {TEXT_SECONDARY};")
        slay.addWidget(task_lbl)

        self.task_picker = TaskPickerButton()
        slay.addWidget(self.task_picker)

        wonder_lbl = QLabel("Wonder3D Mode")
        wonder_lbl.setStyleSheet(f"font-size: 15px; color: {TEXT_SECONDARY};")
        slay.addWidget(wonder_lbl)

        self.combo_wonder3d = QComboBox()
        self.combo_wonder3d.addItems([
            "float32  (high VRAM usage)",
            "float16  (lower VRAM usage)",
        ])
        self.combo_wonder3d.setCurrentIndex(0 if self._run_mode == "remote" else 1)
        self.combo_wonder3d.setStyleSheet(COMBO_STYLE)
        slay.addWidget(self.combo_wonder3d)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {BORDER}; border: none;")
        slay.addWidget(div)

        crop_snaps = [96, 128, 160, 192, 224, 256, 320, 384, 512]
        self.slider_crop   = LabeledSlider("Crop Size",    96,   512,  160, snap_values=crop_snaps)
        self.slider_refine = LabeledSlider("Refine Steps",  0,    10,    0, step=1)

        slay.addWidget(self.slider_crop)
        slay.addWidget(self.slider_refine)

        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {BORDER}; border: none;")
        slay.addWidget(div2)

        self.check_mesh_opt = QCheckBox("Optimize Mesh (LOD generation)")
        self.check_mesh_opt.setChecked(True)
        self.check_mesh_opt.setStyleSheet(self._checkbox_style())
        slay.addWidget(self.check_mesh_opt)

        self.mesh_opt_group = QWidget()
        mog = QVBoxLayout(self.mesh_opt_group)
        mog.setContentsMargins(0, 0, 0, 0)
        mog.setSpacing(12)

        self.slider_faces  = LabeledSlider("Target Faces", 1000, 50000, 8000, step=1000)
        self.slider_stages = LabeledSlider("LOD Stages",   1,    5,     1,    step=1)
        mog.addWidget(self.slider_faces)
        mog.addWidget(self.slider_stages)

        slay.addWidget(self.mesh_opt_group)
        self.check_mesh_opt.toggled.connect(self.mesh_opt_group.setVisible)

        self.check_print = QCheckBox("3D Print mode  (watertight + STL export)")
        self.check_print.setStyleSheet(self._checkbox_style())
        slay.addWidget(self.check_print)

        col.addWidget(settings_card)
        col.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # Run button - always visible, pinned outside scroll
        self.btn_run = QPushButton("START PIPELINE")
        self.btn_run.setFixedHeight(56)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{
                background: {NEON_GREEN}22; border: 2px solid {NEON_GREEN};
                border-radius: 10px; color: {NEON_GREEN};
                font-size: 17px; font-weight: bold; letter-spacing: 2px;
            }}
            QPushButton:hover {{ background: {NEON_GREEN}44; }}
            QPushButton:disabled {{ border-color: {BORDER_BRIGHT}; color: {TEXT_MUTED}; background: transparent; }}
        """)
        self.btn_run.clicked.connect(self.run_requested)
        outer.addWidget(self.btn_run)

        if self._run_mode == "remote":
            self._budget_widget = QWidget()
            blay = QVBoxLayout(self._budget_widget)
            blay.setContentsMargins(0, 4, 0, 0)
            blay.setSpacing(4)

            self._budget_lbl = QLabel("Budget  loading...")
            self._budget_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 13px; letter-spacing: 0.5px;"
            )
            blay.addWidget(self._budget_lbl)

            self._budget_bar = QProgressBar()
            self._budget_bar.setRange(0, 100)
            self._budget_bar.setValue(0)
            self._budget_bar.setTextVisible(False)
            self._budget_bar.setFixedHeight(8)
            self._budget_bar.setStyleSheet(f"""
                QProgressBar {{
                    background: {BG_ELEVATED}; border: 1px solid {BORDER_BRIGHT};
                    border-radius: 4px;
                }}
                QProgressBar::chunk {{ background: {NEON_GREEN}; border-radius: 4px; }}
            """)
            blay.addWidget(self._budget_bar)

            self._budget_widget.setVisible(False)
            outer.addWidget(self._budget_widget)

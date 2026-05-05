from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox
from PySide6.QtCore import Qt

from ui.styles.theme import BG_ELEVATED, BORDER_BRIGHT, CYAN, CYAN_DIM, TEXT_SECONDARY


class LabeledSlider(QWidget):
    """
    Horizontal slider with an editable SpinBox on the right.
    Pass snap_values to constrain the slider to discrete steps.
    """

    def __init__(self, label: str, min_val: int, max_val: int,
                 default: int, step: int = 1,
                 snap_values: list = None, parent=None):
        super().__init__(parent)
        self._snap = snap_values

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        top.addWidget(lbl)
        top.addStretch()

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
            self.slider.valueChanged.connect(lambda v: self.spinbox.setValue(v))
            self.spinbox.editingFinished.connect(self._spinbox_edited)

        layout.addWidget(self.slider)

    def _snap_slider_changed(self, idx: int):
        v = self._snap[idx]
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(v)
        self.spinbox.blockSignals(False)

    def _spinbox_edited_snap(self):
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

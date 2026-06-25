import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy, QFrame, QLabel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtCore import Qt, QUrl, Signal

from ui.styles.theme import (
    BG_DEEP, BG_ELEVATED,
    TEXT_MUTED, TEXT_SECONDARY,
    NEON_ORANGE, BORDER, BORDER_BRIGHT, CYAN,
)
from ui.components.pipeline.helpers import section_label, card


class RightPanel(QWidget):
    cleared = Signal()   # emitted when the user clicks Clear

    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)
        # base_dir is ui/screens/ - viewer lives at project_root/viewer/
        self._viewer_path = os.path.normpath(
            os.path.join(base_dir, "..", "..", "viewer", "index.html")
        )
        self._build()

    # -- Public API ------------------------------------------------------------

    # -- Lifecycle -----------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.web_view.page().setLifecycleState(QWebEnginePage.LifecycleState.Active)
        except Exception:
            pass

    def hideEvent(self, event):
        super().hideEvent(event)
        # Freeze Chromium rendering so two hidden instances don't conflict.
        try:
            self.web_view.page().setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        except Exception:
            pass

    def _js(self, script: str):
        """Run JavaScript, resuming the page first if it was frozen."""
        try:
            page = self.web_view.page()
            if page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
                page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            page.runJavaScript(script)
        except Exception:
            pass

    # -- Public API ------------------------------------------------------------

    def add_model(self, path: str, label: str = None):
        """Add a model to the viewer (shows a toggle button in the sidebar)."""
        file_url = QUrl.fromLocalFile(os.path.abspath(path)).toString()
        label    = (label or os.path.basename(path)).replace("'", "")
        self._js(f"window.addModel('{file_url}', '{label}')")

    def load_model(self, path: str, label: str = None):
        """Load a single model, clearing any previously loaded models."""
        file_url = QUrl.fromLocalFile(os.path.abspath(path)).toString()
        label    = (label or os.path.basename(path)).replace("'", "")
        self._js(f"window.loadModel('{file_url}', '{label}')")

    def clear_models(self):
        self._js("window.clearModels()")
        self._cost_bar.setVisible(False)
        self.cleared.emit()

    def show_print_cost(self, data: dict):
        """Show or hide the print estimate bar below the viewer."""
        if not data:
            self._cost_bar.setVisible(False)
            return
        weight = data.get("estimated_weight_g", 0)
        infill = data.get("infill_pct", 20)
        cost   = data.get("estimated_cost_eur", data.get("estimated_cost_ron", 0))
        self._cost_weight_lbl.setText(f"~{weight}g PLA - {infill}% infill")
        self._cost_price_lbl.setText(f"≈ {cost:.2f} RON")
        self._cost_bar.setVisible(True)

    # -- Build -----------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header row: section label + clear button
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(section_label("3D VIEWER"))
        header_row.addStretch()

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedHeight(24)
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 5px;
                color: {TEXT_MUTED};
                font-size: 11px;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                border-color: {NEON_ORANGE};
                color: {NEON_ORANGE};
            }}
        """)
        btn_clear.clicked.connect(self.clear_models)
        header_row.addWidget(btn_clear)

        layout.addLayout(header_row)
        layout.addSpacing(4)

        viewer_frame = card()
        viewer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vlay = QVBoxLayout(viewer_frame)
        vlay.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView()
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        if os.path.exists(self._viewer_path):
            self.web_view.setUrl(QUrl.fromLocalFile(self._viewer_path))
        else:
            self.web_view.setHtml(self._placeholder())

        vlay.addWidget(self.web_view)
        layout.addWidget(viewer_frame, 1)

        self._cost_bar = self._build_cost_bar()
        layout.addWidget(self._cost_bar)
        self._cost_bar.setVisible(False)

    def _build_cost_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background: {BG_ELEVATED};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 8px;
            }}
        """)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(0)

        tag = QLabel("PRINT ESTIMATE")
        tag.setStyleSheet(
            f"color: {CYAN}; font-size: 11px; letter-spacing: 2px; "
            f"font-weight: bold; background: transparent; border: none;"
        )
        row.addWidget(tag)

        row.addSpacing(14)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {BORDER_BRIGHT}; border: none;")
        row.addWidget(sep)
        row.addSpacing(14)

        self._cost_weight_lbl = QLabel("—")
        self._cost_weight_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        row.addWidget(self._cost_weight_lbl)

        row.addStretch()

        self._cost_price_lbl = QLabel("—")
        self._cost_price_lbl.setStyleSheet(
            f"color: {CYAN}; font-size: 15px; font-weight: bold; background: transparent; border: none;"
        )
        row.addWidget(self._cost_price_lbl)

        return bar

    def _placeholder(self) -> str:
        return (
            f'<html><body style="background:{BG_DEEP};display:flex;align-items:center;'
            f'justify-content:center;height:100vh;margin:0;font-family:monospace;">'
            f'<div style="text-align:center;color:{TEXT_MUTED};">'
            f'<div style="font-size:48px;margin-bottom:16px;">&#x2B21;</div>'
            f'<div style="color:{TEXT_SECONDARY};font-size:14px;">3D Viewer</div>'
            f'<div style="font-size:12px;margin-top:8px;">viewer/index.html not found</div>'
            f'</div></body></html>'
        )

import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtCore import Qt, QUrl, Signal

from ui.styles.theme import BG_DEEP, TEXT_MUTED, TEXT_SECONDARY, NEON_ORANGE, BORDER_BRIGHT
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

    def add_model(self, path: str, label: str = None):
        """Add a model to the viewer (shows a toggle button in the sidebar)."""
        file_url = QUrl.fromLocalFile(os.path.abspath(path)).toString()
        label    = (label or os.path.basename(path)).replace("'", "")
        self.web_view.page().runJavaScript(
            f"window.addModel('{file_url}', '{label}')"
        )

    def load_model(self, path: str, label: str = None):
        """Load a single model, clearing any previously loaded models."""
        file_url = QUrl.fromLocalFile(os.path.abspath(path)).toString()
        label    = (label or os.path.basename(path)).replace("'", "")
        self.web_view.page().runJavaScript(
            f"window.loadModel('{file_url}', '{label}')"
        )

    def clear_models(self):
        self.web_view.page().runJavaScript("window.clearModels()")
        self.cleared.emit()

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

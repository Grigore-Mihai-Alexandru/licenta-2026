from PySide6.QtWidgets import QLabel, QFrame

from ui.styles.theme import BG_SURFACE, BORDER, TEXT_MUTED


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {TEXT_MUTED};
        font-size: 12px;
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

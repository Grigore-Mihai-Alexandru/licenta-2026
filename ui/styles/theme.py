# theme.py — Color palette and global QSS

BG_DEEP        = "#080C18"
BG_BASE        = "#0C1120"
BG_SURFACE     = "#111827"
BG_ELEVATED    = "#1A2235"
BORDER         = "#1E2D45"
BORDER_BRIGHT  = "#2A3F60"

CYAN           = "#00D8FF"
CYAN_DIM       = "#0099BB"
CYAN_GLOW      = "#00D8FF33"
PURPLE         = "#8B5CF6"
NEON_GREEN     = "#00FF88"
NEON_ORANGE    = "#FF6B2B"

TEXT_PRIMARY   = "#E8F0FE"
TEXT_SECONDARY = "#6B7FA3"
TEXT_MUTED     = "#3A4A6A"

GLOBAL_QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_BASE};
    color: {TEXT_PRIMARY};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 18px;
}}
QScrollBar:vertical {{
    background: {BG_SURFACE};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_BRIGHT};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {CYAN_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QPushButton {{
    background-color: transparent;
    border: 1px solid {BORDER_BRIGHT};
    color: {TEXT_PRIMARY};
    border-radius: 8px;
    padding: 10px 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    border-color: {CYAN};
    color: {CYAN};
    background-color: {CYAN_GLOW};
}}
QPushButton:pressed {{ background-color: {CYAN}22; }}
QPushButton:disabled {{ border-color: {BORDER}; color: {TEXT_MUTED}; }}
QTextEdit {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_SECONDARY};
    padding: 12px;
    font-size: 12px;
    selection-background-color: {CYAN}44;
}}
QTextEdit:focus {{ border-color: {CYAN_DIM}; }}
QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {CYAN_DIM};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""

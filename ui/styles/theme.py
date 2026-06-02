# theme.py - "Forge Dark" palette: near-black slate + amber-gold accent

# -- Backgrounds ---------------------------------------------------------------
BG_DEEP        = "#06060F"   # near-true black, faint purple undertone
BG_BASE        = "#0C0C1A"   # main app background
BG_SURFACE     = "#121220"   # card / panel surfaces
BG_ELEVATED    = "#1A1A30"   # inputs, comboboxes, elevated elements

# -- Borders -------------------------------------------------------------------
BORDER         = "#1E1E38"   # subtle separator
BORDER_BRIGHT  = "#2E2E52"   # visible border / focused ring

# -- Primary accent: amber-gold (the "forge" element) -------------------------
CYAN           = "#E8A020"   # amber-gold - used for all interactive highlights
CYAN_DIM       = "#B07818"   # darker amber for pressed / dim states
CYAN_GLOW      = "#E8A02015" # near-transparent amber for background glows

# -- Semantic colors -----------------------------------------------------------
PURPLE         = "#A855F7"   # violet - Drive / secondary actions
NEON_GREEN     = "#10B981"   # emerald-teal - success / DONE states
NEON_ORANGE    = "#EF5340"   # coral-red - errors / warnings

# -- Text ----------------------------------------------------------------------
TEXT_PRIMARY   = "#ECEAFF"   # cool white with faint violet tint
TEXT_SECONDARY = "#B8B8D8"   # readable blue-gray (was too dark)
TEXT_MUTED     = "#8888B0"   # visibly muted but legible (was near-invisible)

# -- Global QSS ----------------------------------------------------------------
GLOBAL_QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_BASE};
    color: {TEXT_PRIMARY};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 16px;
}}
QScrollBar:vertical {{
    background: {BG_SURFACE};
    width: 5px;
    border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_BRIGHT};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {CYAN_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QPushButton {{
    background-color: transparent;
    border: 1px solid {BORDER_BRIGHT};
    color: {TEXT_PRIMARY};
    border-radius: 8px;
    padding: 8px 18px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    border-color: {CYAN};
    color: {CYAN};
    background-color: {CYAN_GLOW};
}}
QPushButton:pressed {{ background-color: {CYAN_DIM}22; }}
QPushButton:disabled {{ border-color: {BORDER}; color: {TEXT_MUTED}; background: transparent; }}
QTextEdit {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_SECONDARY};
    padding: 10px;
    font-size: 14px;
    selection-background-color: {CYAN}44;
}}
QTextEdit:focus {{ border-color: {CYAN_DIM}; }}
QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {CYAN_DIM};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 13px;
}}
"""

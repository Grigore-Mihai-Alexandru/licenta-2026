from ui.styles.theme import (
    BG_ELEVATED, BORDER_BRIGHT,
    CYAN, CYAN_GLOW,
    TEXT_PRIMARY,
)

IDLE    = "idle"
RUNNING = "running"
DONE    = "done"
ERROR   = "error"

VERTEX_DONE_STATES = {
    "JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",  "JOB_STATE_PAUSED",
}

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

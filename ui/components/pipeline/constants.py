from ui.styles.theme import (
    BG_ELEVATED, BORDER_BRIGHT,
    CYAN, CYAN_GLOW,
    TEXT_PRIMARY,
)

IDLE    = "idle"
RUNNING = "running"
DONE    = "done"
ERROR   = "error"
SKIP    = "skip"

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
        padding: 8px 12px;
        font-size: 15px;
        font-family: 'JetBrains Mono', monospace;
        min-height: 36px;
    }}
    QComboBox:hover {{ border-color: {CYAN}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_BRIGHT};
        selection-background-color: {CYAN_GLOW};
        selection-color: {CYAN};
        font-size: 15px;
        padding: 4px;
    }}
"""

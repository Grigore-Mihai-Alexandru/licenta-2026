from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QColor

from CloudBudgetManager import CloudBudgetManager


# -- Worker that refreshes budget from GCS in background ----------------------

class BudgetRefreshWorker(QObject):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, manager: CloudBudgetManager):
        super().__init__()
        self._manager = manager

    def run(self):
        try:
            self._manager.refresh()
            self.finished.emit(self._manager.summary())
        except Exception as exc:
            self.error.emit(str(exc))


# -- Main widget ---------------------------------------------------------------

class BudgetWidget(QWidget):
    """
    Compact panel that shows:
      - monthly spend / limit in USD
      - a color-coded progress bar (green / orange / red)
      - estimated cost of the next job before it is submitted
      - a Refresh button that re-downloads the state from GCS

    Usage
    -----
    Place it anywhere in the cloud panel of the main window.
    Call update_estimate(gpu_type, refine, wonder3d_mode) whenever the
    user changes job parameters so the cost preview stays current.
    Call can_submit() before launching to get the gate result without
    blocking the UI thread.
    """

    def __init__(self, budget_manager: CloudBudgetManager, parent=None):
        super().__init__(parent)
        self._manager = budget_manager
        self._last_summary: dict = {}
        self._build_ui()
        self.refresh()

    # -- UI construction -------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(0, 0, 0, 0)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel("Monthly GPU budget")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        title_row.addWidget(title)
        title_row.addStretch()

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedWidth(70)
        self._btn_refresh.setToolTip("Re-download budget state from GCS")
        self._btn_refresh.clicked.connect(self.refresh)
        title_row.addWidget(self._btn_refresh)
        root.addLayout(title_row)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(14)
        root.addWidget(self._bar)

        # Labels row: spent / remaining
        label_row = QHBoxLayout()
        self._lbl_spent = QLabel("--")
        self._lbl_remaining = QLabel("--")
        self._lbl_remaining.setAlignment(Qt.AlignRight)
        label_row.addWidget(self._lbl_spent)
        label_row.addStretch()
        label_row.addWidget(self._lbl_remaining)
        root.addLayout(label_row)

        # Estimate row
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        self._lbl_estimate = QLabel("Estimated job cost:  --")
        self._lbl_estimate.setToolTip("Conservative estimate based on GPU type and refinement level")
        root.addWidget(self._lbl_estimate)

        self._lbl_status = QLabel("")
        root.addWidget(self._lbl_status)

    # -- Refresh from GCS ------------------------------------------------------

    def refresh(self):
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.setText("...")

        self._thread = QThread(self)
        self._worker = BudgetRefreshWorker(self._manager)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_refresh_done)
        self._worker.error.connect(self._on_refresh_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker.deleteLater)

        self._thread.start()

    def _on_refresh_done(self, summary: dict):
        self._last_summary = summary
        self._apply_summary(summary)
        self._btn_refresh.setEnabled(True)
        self._btn_refresh.setText("Refresh")

    def _on_refresh_error(self, msg: str):
        self._lbl_status.setText(f"Refresh error: {msg}")
        self._btn_refresh.setEnabled(True)
        self._btn_refresh.setText("Refresh")

    def _apply_summary(self, summary: dict):
        spent = summary.get("spent_usd", 0.0)
        limit = summary.get("monthly_limit_usd", 1.0)
        remaining = summary.get("remaining_usd", 0.0)
        pct = summary.get("usage_percent", 0.0)
        month = summary.get("month", "")
        jobs = summary.get("jobs_count", 0)

        self._bar.setValue(int(min(pct, 100)))
        self._set_bar_color(pct)

        self._lbl_spent.setText(
            f"Spent ({month}):  ${spent:.2f} / ${limit:.2f}  ({pct:.1f}%)"
        )
        self._lbl_remaining.setText(f"Remaining: ${remaining:.2f}")
        self._lbl_status.setText(f"{jobs} job(s) recorded this month")

    def _set_bar_color(self, pct: float):
        if pct < 60:
            color = "#4caf50"
        elif pct < 85:
            color = "#ff9800"
        else:
            color = "#f44336"

        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}"
        )

    # -- Estimate preview ------------------------------------------------------

    def update_estimate(self, gpu_type: str, refine: int, wonder3d_mode: str = "official"):
        """
        Call this whenever the user changes GPU type or refine level.
        Updates the cost preview without touching GCS.
        """
        cost = self._manager.estimate_job_cost(gpu_type, refine, wonder3d_mode)
        rem = self._manager.remaining()
        affordable = rem >= cost

        self._lbl_estimate.setText(
            f"Estimated job cost:  ${cost:.2f}  (remaining: ${rem:.2f})"
        )

        if affordable:
            self._lbl_estimate.setStyleSheet("color: inherit;")
        else:
            self._lbl_estimate.setStyleSheet("color: #f44336; font-weight: bold;")

    # -- Gate check called before submission -----------------------------------

    def can_submit(self, gpu_type: str, refine: int, wonder3d_mode: str = "official") -> bool:
        """
        Checks local (already-downloaded) state.
        Returns True if the budget allows the job.
        Shows a blocking QMessageBox if budget is exceeded.
        Always call refresh() before showing the submit dialog
        so the cached state is fresh.
        """
        allowed, cost, remaining = self._manager.can_submit(gpu_type, refine, wonder3d_mode)
        if not allowed:
            summary = self._manager.summary()
            QMessageBox.warning(
                self,
                "Monthly budget exceeded",
                f"This job would cost approximately ${cost:.2f}.\n"
                f"You have ${remaining:.2f} remaining of your "
                f"${summary['monthly_limit_usd']:.2f} monthly limit.\n\n"
                f"Budget resets on the 1st of the next month.",
            )
        return allowed
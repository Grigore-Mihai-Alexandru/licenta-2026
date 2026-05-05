from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QListWidget, QListWidgetItem,
    QFileDialog, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl

from DriveManager import DriveManager
import os


# -- Workers -------------------------------------------------------------------

class UploadWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, manager: DriveManager, file_paths: list[str]):
        super().__init__()
        self._manager = manager
        self._paths = file_paths

    def run(self):
        try:
            uploaded = self._manager.upload_results(
                self._paths,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(uploaded)
        except Exception as exc:
            self.error.emit(str(exc))


class DownloadWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, manager: DriveManager, uploaded: list[dict], dest_dir: str):
        super().__init__()
        self._manager = manager
        self._uploaded = uploaded
        self._dest = dest_dir

    def run(self):
        try:
            downloaded = self._manager.download_results(
                self._uploaded,
                self._dest,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(downloaded)
        except Exception as exc:
            self.error.emit(str(exc))


# -- Panel widget --------------------------------------------------------------

class DrivePanel(QWidget):
    """
    Self-contained panel for Google Drive file operations.

    Workflow:
      1. After a job finishes, call set_result_paths(paths) with
         the local file paths produced by the pipeline.
      2. The user clicks 'Upload to Drive' - files go to the
         'Neural Forge' folder in their Drive.
      3. The user optionally clicks 'Download to PC' to save
         the same files to a local directory they choose.
      4. 'Open in Drive' opens the Neural Forge folder in the browser.
    """

    def __init__(self, drive_manager: DriveManager, parent=None):
        super().__init__(parent)
        self._manager = drive_manager
        self._result_paths: list[str] = []
        self._uploaded: list[dict] = []
        self._build_ui()

    # -- Construction ----------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("Google Drive")
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        # File list
        self._list = QListWidget()
        self._list.setFixedHeight(100)
        self._list.setToolTip("Files queued for upload")
        root.addWidget(self._list)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(16)
        self._bar.hide()
        root.addWidget(self._bar)

        # Status label
        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Buttons row
        btn_row = QHBoxLayout()

        self._btn_upload = QPushButton("Upload to Drive")
        self._btn_upload.setEnabled(False)
        self._btn_upload.setToolTip("Upload pipeline results to your Neural Forge folder in Google Drive")
        self._btn_upload.clicked.connect(self._start_upload)
        btn_row.addWidget(self._btn_upload)

        self._btn_download = QPushButton("Download to PC")
        self._btn_download.setEnabled(False)
        self._btn_download.setToolTip("Download the uploaded files from Drive to a local folder")
        self._btn_download.clicked.connect(self._start_download)
        btn_row.addWidget(self._btn_download)

        self._btn_open_drive = QPushButton("Open in Drive")
        self._btn_open_drive.setToolTip("Open the Neural Forge folder in your browser")
        self._btn_open_drive.clicked.connect(self._open_drive)
        btn_row.addWidget(self._btn_open_drive)

        root.addLayout(btn_row)

    # -- Public API ------------------------------------------------------------

    def set_result_paths(self, paths: list[str]):
        """
        Call this after the pipeline finishes to populate the file list.
        Filters out paths that do not exist on disk.
        """
        self._result_paths = [p for p in paths if p and os.path.exists(p)]
        self._uploaded = []
        self._list.clear()
        self._btn_download.setEnabled(False)

        for path in self._result_paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            self._list.addItem(item)

        has_files = bool(self._result_paths)
        self._btn_upload.setEnabled(has_files)
        self._lbl_status.setText(
            f"{len(self._result_paths)} file(s) ready to upload."
            if has_files
            else "No output files found."
        )

    # -- Upload ----------------------------------------------------------------

    def _start_upload(self):
        if not self._result_paths:
            return
        self._set_busy(True)
        self._bar.setValue(0)
        self._bar.show()
        self._lbl_status.setText("Uploading...")

        self._thread = QThread()
        self._worker = UploadWorker(self._manager, self._result_paths)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_upload_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

    def _on_upload_done(self, uploaded: list[dict]):
        self._uploaded = uploaded
        self._bar.setValue(100)
        self._lbl_status.setText(
            f"Uploaded {len(uploaded)} file(s) to Drive successfully."
        )
        self._btn_download.setEnabled(bool(uploaded))
        self._set_busy(False)

    # -- Download --------------------------------------------------------------

    def _start_download(self):
        if not self._uploaded:
            return

        dest_dir = QFileDialog.getExistingDirectory(
            self,
            "Select download folder",
            os.path.expanduser("~"),
        )
        if not dest_dir:
            return

        self._set_busy(True)
        self._bar.setValue(0)
        self._bar.show()
        self._lbl_status.setText("Downloading...")

        self._thread = QThread()
        self._worker = DownloadWorker(self._manager, self._uploaded, dest_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_download_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

    def _on_download_done(self, paths: list[str]):
        self._bar.setValue(100)
        self._lbl_status.setText(
            f"Downloaded {len(paths)} file(s):\n{paths[0] if paths else ''}"
        )
        self._set_busy(False)

    # -- Open in browser -------------------------------------------------------

    def _open_drive(self):
        try:
            link = self._manager.get_folder_link()
            QDesktopServices.openUrl(QUrl(link))
        except Exception as exc:
            QMessageBox.warning(self, "Drive error", str(exc))

    # -- Shared helpers --------------------------------------------------------

    def _on_progress(self, filename: str, pct: int):
        self._bar.setValue(pct)
        self._lbl_status.setText(f"{filename}  {pct}%")

    def _on_error(self, msg: str):
        self._bar.hide()
        self._lbl_status.setText(f"Error: {msg}")
        self._set_busy(False)
        QMessageBox.critical(self, "Drive error", msg)

    def _set_busy(self, busy: bool):
        self._btn_upload.setEnabled(not busy and bool(self._result_paths))
        self._btn_download.setEnabled(not busy and bool(self._uploaded))
        self._btn_open_drive.setEnabled(not busy)
        self._btn_refresh_state = busy
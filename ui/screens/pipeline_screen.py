import os
import sys
from datetime import datetime

from PySide6.QtCore import QTimer, QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from ui.styles.theme import NEON_GREEN, NEON_ORANGE, CYAN
from ui.components.pipeline import (
    IDLE, RUNNING, DONE, ERROR,
    VERTEX_DONE_STATES,
    GCSDownloadWorker, DriveWorker, DriveAuthWorker,
    DockerBuildWorker, DockerRunWorker,
    BudgetFetchWorker,
    TopBar, LeftPanel, CenterPanel, RightPanel,
)

# Extensions that are loadable in the 3D viewer
_VIEWER_EXTS  = {".glb", ".obj"}
# Extensions collected as pipeline results (includes viewer + report + stl)
_RESULT_EXTS  = {".glb", ".obj", ".stl", ".json"}


def _model_label(path: str) -> str:
    name = os.path.basename(path)
    if "lowpoly" in name.lower():
        return "Optimized"
    if name.lower().startswith("model"):
        return "Original"
    return os.path.splitext(name)[0]


class PipelineScreen(QWidget):
    logout_requested = Signal()

    def __init__(self, run_mode: str = "local", credentials=None,
                 user_info: dict = None, parent=None):
        super().__init__(parent)
        self.run_mode    = run_mode
        self.credentials = credentials
        self.user_info   = user_info or {}
        self.base_dir    = os.path.dirname(os.path.abspath(__file__))
        self.project_dir = os.path.abspath(os.path.join(self.base_dir, "..", ".."))

        # Vertex AI polling
        self._vertex_job  = None
        self._poll_timer  = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_vertex_job)

        # Worker threads (one per slot, replaced each run)
        self._docker_build_thread  = None
        self._docker_build_worker  = None
        self._docker_run_thread    = None
        self._docker_run_worker    = None
        self._budget_thread        = None
        self._budget_worker        = None
        self._gcs_thread           = None
        self._gcs_worker           = None
        self._drive_auth_thread    = None
        self._drive_auth_worker    = None
        self._drive_thread         = None
        self._drive_worker         = None

        self._result_paths:  list = []
        self._job_name       = None
        self._input_basename = None

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = TopBar(self.run_mode, self.user_info)
        root.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(12)
        root.addLayout(body)

        self.left   = LeftPanel(run_mode=self.run_mode)
        self.center = CenterPanel()
        self.right  = RightPanel(base_dir=self.base_dir)

        body.addWidget(self.left,   2)
        body.addWidget(self.center, 2)
        body.addWidget(self.right,  4)

        self.left.run_requested.connect(self._start_pipeline)
        self.left.image_loaded.connect(
            lambda p: self._log(f"[INPUT] Loaded: {os.path.basename(p)}")
        )
        self.center.save_requested.connect(self._save_to_drive)

        if self.run_mode == "remote":
            self._refresh_budget()

    # ── Pipeline start ─────────────────────────────────────────────────────────

    def _start_pipeline(self):
        if not self.left.image_path:
            self._log("[ERROR] No image selected.", NEON_ORANGE)
            return

        settings = self.left.get_settings()
        self._log(
            f"[CONFIG] tasks={settings['restormer_tasks']}, "
            f"wonder3d={settings['wonder3d_mode']}, "
            f"crop={settings['crop']}, refine={settings['refine']}, "
            f"mesh_opt={settings['mesh_optimize']}"
            + (f", faces={settings['faces']}, stages={settings['stages']}"
               if settings['mesh_optimize'] else "")
        )

        name_no_ext    = os.path.splitext(os.path.basename(self.left.image_path))[0]
        self._job_name = f"{name_no_ext}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"

        self.left.set_controls_enabled(False)
        self.center.show_save_button(visible=False)
        self.right.clear_models()
        self._result_paths = []
        self.center.set_all_steps(IDLE)

        if self.run_mode == "local":
            self._run_local(settings)
        else:
            self._run_cloud(**settings)

    # ── Local — Docker ─────────────────────────────────────────────────────────

    def _run_local(self, settings: dict):
        self._log("[LOCAL] Checking Docker image...")
        self.center.set_job_status("Checking Docker image...", CYAN)

        self._docker_build_thread = QThread()
        self._docker_build_worker = DockerBuildWorker(self.project_dir)
        self._docker_build_worker.moveToThread(self._docker_build_thread)

        self._docker_build_thread.started.connect(self._docker_build_worker.run)
        self._docker_build_worker.log.connect(self._log)
        self._docker_build_worker.finished.connect(
            lambda ok: self._on_build_done(ok, settings)
        )
        self._docker_build_worker.finished.connect(self._docker_build_thread.quit)

        self._docker_build_thread.start()

    def _on_build_done(self, success: bool, settings: dict):
        if not success:
            self._log("[LOCAL] Docker image build failed.", NEON_ORANGE)
            self._on_pipeline_done(success=False)
            return

        output_dir = os.path.join(
            os.path.expanduser("~"), "Downloads", "NeuralForge", self._job_name
        )
        self._log(f"[LOCAL] Starting pipeline — output: {output_dir}")
        self.center.set_job_status("Running pipeline...", CYAN)
        self.center.set_all_steps(RUNNING)

        self._docker_run_thread = QThread()
        self._docker_run_worker = DockerRunWorker(
            image_path=self.left.image_path,
            output_dir=output_dir,
            settings=settings,
        )
        self._docker_run_worker.moveToThread(self._docker_run_thread)

        self._docker_run_thread.started.connect(self._docker_run_worker.run)
        self._docker_run_worker.log.connect(self._log)
        self._docker_run_worker.step_done.connect(
            lambda idx: self.center.set_step_state(idx, DONE)
        )
        self._docker_run_worker.finished.connect(self._on_docker_run_done)
        self._docker_run_worker.finished.connect(self._docker_run_thread.quit)

        self._docker_run_thread.start()
        self._input_basename = os.path.basename(self.left.image_path)

    def _on_docker_run_done(self, success: bool):
        if success:
            # Scan output dir for results
            output_dir = os.path.join(
                os.path.expanduser("~"), "Downloads", "NeuralForge", self._job_name
            )
            self._result_paths = self._collect_results(output_dir)
            self._log(f"[OUTPUT] Found {len(self._result_paths)} result file(s).")
        self._on_pipeline_done(success=success)

    # ── Cloud — Vertex AI ──────────────────────────────────────────────────────

    def _run_cloud(self, restormer_tasks, wonder3d_mode, crop, refine,
                   faces, stages, mesh_optimize, print_mode):
        try:
            cloud_dir = os.path.abspath(os.path.join(self.base_dir, "..", "..", "cloud"))
            if cloud_dir not in sys.path:
                sys.path.insert(0, cloud_dir)

            manager = self.credentials
            email   = self.user_info.get("email", "unknown")

            budget  = manager.build_budget_manager(user_email=email)
            summary = budget.summary()
            self._log(
                f"[BUDGET] {email} — spent ${summary['spent_usd']:.2f} / "
                f"${summary['monthly_limit_usd']:.2f} this month"
            )

            cloud_uri = manager.upload_file(self.left.image_path)
            image_uri = manager.setup_artifact_registry()

            self._input_basename = os.path.basename(self.left.image_path)

            self._vertex_job = manager.launch_vertex_job(
                image_uri=image_uri,
                input_uri=cloud_uri,
                crop_size=crop,
                refine=refine,
                mesh_faces=faces,
                mesh_stages=stages,
                mesh_optimize=mesh_optimize,
                wonder3d_mode=wonder3d_mode,
                restormer_tasks=restormer_tasks,
                budget_manager=budget,
            )

            job_id = self._vertex_job.resource_name.split("/")[-1]
            self._log(f"[CLOUD] Job submitted: {job_id}")
            self._log(f"[CLOUD] Drive folder: Neural Forge/{self._job_name}/")
            self.center.set_job_status("Submitted — waiting for GPU...", CYAN)
            self.center.set_job_id(self._vertex_job.resource_name)
            self.center.set_all_steps(RUNNING)

            QTimer.singleShot(60_000, self._cleanup_gcs_inputs)
            self._poll_timer.start(30_000)

        except RuntimeError as e:
            self._log(f"[BUDGET ERROR] {e}", NEON_ORANGE)
            self._on_pipeline_done(success=False)
        except Exception as e:
            self._log(f"[ERROR] {e}", NEON_ORANGE)
            self._on_pipeline_done(success=False)

    # ── Budget ────────────────────────────────────────────────────────────────

    def _refresh_budget(self):
        if not self.credentials:
            return
        email = self.user_info.get("email", "")
        if not email:
            # Fallback: re-fetch user info in case it failed at login
            try:
                info  = self.credentials.get_user_info()
                email = info.get("email", "")
                if email:
                    self.user_info = info
            except Exception:
                pass
        if not email:
            return

        self._budget_thread = QThread()
        self._budget_worker = BudgetFetchWorker(self.credentials, email)
        self._budget_worker.moveToThread(self._budget_thread)

        self._budget_thread.started.connect(self._budget_worker.run)
        self._budget_worker.finished.connect(self._on_budget_fetched)
        self._budget_worker.error.connect(
            lambda e: self._log(f"[BUDGET] Could not load budget: {e}")
        )
        self._budget_worker.finished.connect(self._budget_thread.quit)
        self._budget_worker.error.connect(self._budget_thread.quit)

        self._budget_thread.start()

    def _on_budget_fetched(self, summary: dict):
        self.left.set_budget(
            spent=summary["spent_usd"],
            limit=summary["monthly_limit_usd"],
            jobs=summary["jobs_count"],
        )

    # ── Vertex AI polling ──────────────────────────────────────────────────────

    def _poll_vertex_job(self):
        if not self._vertex_job:
            self._poll_timer.stop()
            return
        try:
            self._vertex_job.refresh()
            state = self._vertex_job.state.name
            self._log(f"[POLL] Job state: {state}")
            self.center.set_job_status(f"Job: {state}", CYAN)

            if state == "JOB_STATE_SUCCEEDED":
                self._poll_timer.stop()
                self.center.set_all_steps(DONE)
                self._log("[CLOUD] Job succeeded!", NEON_GREEN)
                self._start_gcs_download()
            elif state in VERTEX_DONE_STATES:
                self._poll_timer.stop()
                self.center.set_all_steps(ERROR)
                self._log(f"[CLOUD] Job ended: {state}", NEON_ORANGE)
                self._on_pipeline_done(success=False)

        except Exception as e:
            self._log(f"[POLL ERROR] {e}", NEON_ORANGE)

    # ── GCS download ──────────────────────────────────────────────────────────

    def _start_gcs_download(self):
        local_dir = os.path.join(
            os.path.expanduser("~"), "Downloads", "NeuralForge", self._job_name
        )
        self._log(f"[GCS] Downloading results to {local_dir}...")
        self.center.set_job_status("Downloading results from GCS...", CYAN)

        self._gcs_thread = QThread()
        self._gcs_worker = GCSDownloadWorker(self.credentials, local_dir)
        self._gcs_worker.moveToThread(self._gcs_thread)

        self._gcs_thread.started.connect(self._gcs_worker.run)
        self._gcs_worker.finished.connect(self._on_gcs_download_done)
        self._gcs_worker.error.connect(self._on_gcs_download_error)
        self._gcs_worker.finished.connect(self._gcs_thread.quit)
        self._gcs_worker.error.connect(self._gcs_thread.quit)

        self._gcs_thread.start()

    def _on_gcs_download_done(self, paths: list):
        self._log(f"[GCS] Downloaded {len(paths)} file(s).", NEON_GREEN)
        self._result_paths = paths
        self._on_pipeline_done(success=True)

    def _on_gcs_download_error(self, msg: str):
        self._log(f"[GCS ERROR] {msg}", NEON_ORANGE)
        self._on_pipeline_done(success=False)

    # ── GCS cleanup ───────────────────────────────────────────────────────────

    def _cleanup_gcs_inputs(self):
        try:
            self.credentials.delete_gcs_inputs(self._input_basename)
            self._log("[GCS] Input cleaned from bucket.")
        except Exception as e:
            self._log(f"[GCS] Input cleanup failed: {e}")

    def _cleanup_gcs_outputs(self):
        try:
            self.credentials.delete_gcs_outputs()
            self._log("[GCS] Outputs cleaned from bucket.")
        except Exception as e:
            self._log(f"[GCS] Output cleanup failed: {e}")

    # ── Pipeline done ─────────────────────────────────────────────────────────

    def _on_pipeline_done(self, success: bool):
        self.left.set_controls_enabled(True)

        if success:
            self._log("[PIPELINE] Complete!", NEON_GREEN)
            self.center.set_job_status("Completed", NEON_GREEN)

            if self._result_paths:
                self.center.show_save_button(visible=True, n_files=len(self._result_paths))
                self._load_results_into_viewer(self._result_paths)
        else:
            self._log("[PIPELINE] Failed.", NEON_ORANGE)
            self.center.set_job_status("Failed", NEON_ORANGE)

        if self.run_mode == "remote":
            self._refresh_budget()

    # ── Viewer helpers ────────────────────────────────────────────────────────

    def _collect_results(self, directory: str) -> list:
        """Walk directory tree and collect all pipeline output files."""
        results = []
        for root, _, files in os.walk(directory):
            for f in files:
                if os.path.splitext(f)[1].lower() in _RESULT_EXTS:
                    results.append(os.path.join(root, f))
        return results

    def _load_results_into_viewer(self, paths: list):
        """Add every loadable 3D model to the viewer with smart labels."""
        loaded = 0
        for path in paths:
            if os.path.splitext(path)[1].lower() in _VIEWER_EXTS:
                label = _model_label(path)
                self.right.add_model(path, label)
                self._log(f"[VIEWER] Added: {label} ({os.path.basename(path)})")
                loaded += 1
        if loaded == 0:
            self._log("[VIEWER] No 3D models found to display.")

    # ── Drive upload ──────────────────────────────────────────────────────────

    def _save_to_drive(self):
        if not self._result_paths:
            self._log("[DRIVE] No result files to upload.", NEON_ORANGE)
            return

        self.center.set_save_enabled(False)

        if self.run_mode == "local":
            # Local mode has no CloudManager — authenticate via OAuth first
            secrets_path = os.path.join(self.project_dir, "cloud", "client_secrets.json")
            token_path   = os.path.join(self.project_dir, "cloud", "token.pickle")

            if not os.path.exists(secrets_path):
                self._log(
                    "[DRIVE ERROR] cloud/client_secrets.json not found. "
                    "Drive upload requires a Google OAuth credentials file.",
                    NEON_ORANGE,
                )
                self.center.set_save_enabled(True)
                return

            self._log("[DRIVE] Authenticating with Google...")
            self._drive_auth_thread = QThread()
            self._drive_auth_worker = DriveAuthWorker(secrets_path, token_path)
            self._drive_auth_worker.moveToThread(self._drive_auth_thread)

            self._drive_auth_thread.started.connect(self._drive_auth_worker.run)
            self._drive_auth_worker.success.connect(self._on_drive_auth_done)
            self._drive_auth_worker.error.connect(self._on_drive_auth_error)
            self._drive_auth_worker.success.connect(self._drive_auth_thread.quit)
            self._drive_auth_worker.error.connect(self._drive_auth_thread.quit)

            self._drive_auth_thread.start()
        else:
            creds = self.credentials.creds if hasattr(self.credentials, "creds") else self.credentials
            self._start_drive_upload(creds)

    def _on_drive_auth_done(self, creds):
        self._log("[DRIVE] Authenticated.", NEON_GREEN)
        self._start_drive_upload(creds)

    def _on_drive_auth_error(self, message: str):
        self._log(f"[DRIVE ERROR] Authentication failed: {message}", NEON_ORANGE)
        self.center.set_save_enabled(True)

    def _start_drive_upload(self, creds):
        job_name = self._job_name or "results"
        self._log(f"[DRIVE] Uploading {len(self._result_paths)} file(s) -> Neural Forge/{job_name}/")

        self._drive_thread = QThread()
        self._drive_worker = DriveWorker(creds, self._result_paths, job_name)
        self._drive_worker.moveToThread(self._drive_thread)

        self._drive_thread.started.connect(self._drive_worker.run)
        self._drive_worker.progress.connect(
            lambda fname, pct: self._log(f"[DRIVE] {fname} — {pct}%")
        )
        self._drive_worker.finished.connect(self._on_drive_done)
        self._drive_worker.error.connect(self._on_drive_error)
        self._drive_worker.finished.connect(self._drive_thread.quit)
        self._drive_worker.error.connect(self._drive_thread.quit)

        self._drive_thread.start()

    def _on_drive_done(self, uploaded: list):
        self.center.set_save_enabled(True)
        job_name = self._job_name or "results"
        self._log(
            f"[DRIVE] {len(uploaded)} file(s) saved to Neural Forge/{job_name}/",
            NEON_GREEN,
        )
        self.center.set_job_status("Saved to Drive", NEON_GREEN)
        if self.run_mode == "remote":
            QTimer.singleShot(500, self._cleanup_gcs_outputs)

    def _on_drive_error(self, message: str):
        self.center.set_save_enabled(True)
        self._log(f"[DRIVE ERROR] {message}", NEON_ORANGE)

    # ── Public API ────────────────────────────────────────────────────────────

    def _log(self, message: str, color: str = None):
        self.center.log(message, color)

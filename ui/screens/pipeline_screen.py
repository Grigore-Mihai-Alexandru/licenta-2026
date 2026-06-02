import os
import sys
from datetime import datetime

from PySide6.QtCore import QTimer, QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QMessageBox

from ui.styles.theme import NEON_GREEN, NEON_ORANGE, CYAN
from ui.components.pipeline import (
    IDLE, RUNNING, DONE, ERROR,
    VERTEX_DONE_STATES,
    GCSDownloadWorker, DriveWorker, DriveAuthWorker,
    DockerBuildWorker, DockerRunWorker,
    BudgetFetchWorker,
    TopBar, LeftPanel, CenterPanel, RightPanel,
)

_VIEWER_EXTS = {".glb", ".obj"}
_RESULT_EXTS = {".glb", ".obj", ".stl", ".json"}

_VERTEX_STATE_LABELS = {
    "JOB_STATE_PENDING":   ("Starting - pulling container image...", CYAN),
    "JOB_STATE_QUEUED":    ("Queued on GPU cluster...", CYAN),
    "JOB_STATE_RUNNING":   ("Pipeline running on GPU...", NEON_GREEN),
    "JOB_STATE_SUCCEEDED": ("Complete!", NEON_GREEN),
    "JOB_STATE_FAILED":    ("Job failed.", NEON_ORANGE),
    "JOB_STATE_CANCELLED": ("Job cancelled.", NEON_ORANGE),
}


def _model_label(path: str) -> str:
    name = os.path.basename(path)
    if "lowpoly" in name.lower():
        return "Optimized"
    if name.lower().startswith("model"):
        return "Original"
    return os.path.splitext(name)[0]


class PipelineScreen(QWidget):
    logout_requested = Signal()
    home_requested   = Signal()
    notification     = Signal(str, str)
    signed_out       = Signal()   # cloud sign-out: credentials cleared, go home

    def __init__(self, run_mode: str = "local", credentials=None,
                 user_info: dict = None, parent=None):
        super().__init__(parent)
        self.run_mode    = run_mode
        self.credentials = credentials
        self.user_info   = user_info or {}
        self.base_dir    = os.path.dirname(os.path.abspath(__file__))
        self.project_dir = os.path.abspath(os.path.join(self.base_dir, "..", ".."))

        # Vertex AI polling
        self._vertex_job        = None
        self._poll_timer        = QTimer(self)
        self._poll_fast_ticks   = 0
        self._last_vertex_state = ""
        self._poll_timer.timeout.connect(self._poll_vertex_job)

        # Drive state - shared between local and cloud modes
        self._drive_creds = None
        self._drive_email = ""

        # Worker threads
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
        self._history_panel  = None

        # Queue state (cloud mode)
        self._job_queue           = None   # JobQueue instance
        self._queue_entry_id      = None   # our GCS queue entry blob name
        self._holds_lock          = False  # True while we hold the GPU lock
        self._pending_cloud_params = None  # stored job params to submit when turn arrives
        self._queue_timer         = QTimer(self)
        self._queue_timer.timeout.connect(self._poll_queue)

        self._build()

        # Set initial Drive section state
        if self.run_mode == "remote":
            self._init_cloud_drive()
        else:
            self.center.set_drive_state("connect")

    # Layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = TopBar(self.run_mode, self.user_info)
        self.top_bar.home_requested.connect(self.home_requested)
        self.top_bar.history_requested.connect(self._show_history)
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
        self.center.upload_to_drive_requested.connect(self._save_to_drive)
        self.center.cancel_requested.connect(self._cancel_pipeline)
        self.right.cleared.connect(self._on_viewer_cleared)
        self.top_bar.sign_out_requested.connect(self._sign_out_cloud)
        self.top_bar.connect_drive_requested.connect(self._connect_drive)
        self.top_bar.disconnect_drive_requested.connect(self._disconnect_drive)

        if self.run_mode == "remote":
            self._refresh_budget()

    # Drive initialisation

    def _init_cloud_drive(self):
        """Pre-populate Drive creds from the cloud manager (cloud mode only)."""
        try:
            creds = getattr(self.credentials, "creds", None)
            # Sanity-check: must be a google.oauth2.credentials.Credentials-like object
            # (has 'token' attr), not the CloudManager itself or None.
            if creds is None or not hasattr(creds, "token"):
                self._log("[DRIVE] Cloud credentials not suitable for Drive - use Login button.", NEON_ORANGE)
                self.center.set_drive_state("connect")
                return
            self._drive_creds = creds
            self._drive_email = self.user_info.get("email", "")
            self.center.set_drive_state("connected", email=self._drive_email)
        except Exception as e:
            self._log(f"[DRIVE] Could not pre-load Drive credentials: {e}")
            self.center.set_drive_state("connect")

        # Auto-detect persistent GPU resource in background
        QTimer.singleShot(2000, self._probe_persistent_resource)

    def _probe_persistent_resource(self):
        """Called 2s after startup - silent version of _sync_persistent_resource."""
        try:
            self._sync_persistent_resource(self.credentials, log=True)
        except Exception:
            pass

    def _sync_persistent_resource(self, manager, log: bool = False):
        """
        Read cloud/.demo-gpu-state.json and configure manager.vertex_region +
        manager._persistent_resource_id to match whatever manage_gpu.py created.
        Safe to call repeatedly - always reflects the current state file.
        """
        import json as _json
        state_file = os.path.join(self.project_dir, "cloud", ".demo-gpu-state.json")

        if not os.path.exists(state_file):
            manager._persistent_resource_id = None
            return

        try:
            with open(state_file) as f:
                saved = _json.load(f)
        except Exception:
            return

        region = saved.get("region")
        if not region:
            return

        manager.vertex_region = region

        state = manager.get_persistent_resource_state("demo-gpu")
        gpu_type = saved.get("gpu", "l4").upper()   # "l4"/"t4" -> "L4"/"T4"

        if state == "RUNNING":
            manager.use_persistent_resource("demo-gpu", gpu_type=gpu_type)
            if log:
                self._log(
                    f"[GPU] Persistent cluster RUNNING in {region} ({gpu_type}) - jobs start in ~15-30s.",
                    NEON_GREEN,
                )
        else:
            manager._persistent_resource_id = None
            if log and state == "PROVISIONING":
                self._log(f"[GPU] Persistent cluster still provisioning in {region}...", CYAN)
            elif log and state not in ("NOT_FOUND", "UNKNOWN"):
                self._log(f"[GPU] Persistent cluster state: {state} in {region}.", NEON_ORANGE)

    # Sign-out

    def _sign_out_cloud(self):
        """Cloud mode: confirm, wipe token, go back to welcome."""
        from PySide6.QtWidgets import QMessageBox
        email = self.user_info.get("email", "your account")
        reply = QMessageBox.question(
            self,
            "Sign Out",
            f"Sign out of {email}?\n\nYou will need to log in again next time.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        token_path = os.path.join(self.project_dir, "cloud", "token.pickle")
        try:
            if os.path.exists(token_path):
                os.remove(token_path)
        except Exception as e:
            self._log(f"[AUTH] Could not delete token: {e}", NEON_ORANGE)

        self.signed_out.emit()

    def _disconnect_drive(self):
        """Drive disconnect: wipe token, reset Drive section and top-bar widget."""
        token_path = os.path.join(self.project_dir, "cloud", "token.pickle")
        try:
            if os.path.exists(token_path):
                os.remove(token_path)
        except Exception as e:
            self._log(f"[DRIVE] Could not delete token: {e}", NEON_ORANGE)

        self._drive_creds = None
        self._drive_email = ""
        self.center.set_drive_state("connect")
        self.top_bar.set_drive_disconnected()
        self._log("[DRIVE] Disconnected. Use the Connect Drive button to switch accounts.")

    # Drive connect (explicit login)

    def _connect_drive(self):
        """Runs DriveAuthWorker to authenticate (used for local mode or re-auth)."""
        secrets_path = os.path.join(self.project_dir, "cloud", "client_secrets.json")
        token_path   = os.path.join(self.project_dir, "cloud", "token.pickle")

        if not os.path.exists(secrets_path):
            self._log("[DRIVE ERROR] cloud/client_secrets.json not found.", NEON_ORANGE)
            return

        self.center.set_drive_state("connecting")
        self._log("[DRIVE] Authenticating with Google Drive...")

        self._drive_auth_thread = QThread()
        self._drive_auth_worker = DriveAuthWorker(secrets_path, token_path)
        self._drive_auth_worker.moveToThread(self._drive_auth_thread)

        self._drive_auth_thread.started.connect(self._drive_auth_worker.run)
        self._drive_auth_worker.success.connect(self._on_drive_connect_success)
        self._drive_auth_worker.error.connect(self._on_drive_connect_error)
        self._drive_auth_worker.success.connect(self._drive_auth_thread.quit)
        self._drive_auth_worker.error.connect(self._drive_auth_thread.quit)

        self._drive_auth_thread.start()

    def _on_drive_connect_success(self, creds, email: str):
        self._drive_creds = creds
        self._drive_email = email
        self._log(f"[DRIVE] Connected as {email or 'unknown'}.", NEON_GREEN)
        self.top_bar.set_drive_connected(email)

        if self._result_paths:
            self.center.set_drive_state("ready", n_files=len(self._result_paths))
        else:
            self.center.set_drive_state("connected")

    def _on_drive_connect_error(self, message: str):
        self._log(f"[DRIVE ERROR] Authentication failed: {message}", NEON_ORANGE)
        self.center.set_drive_state("connect")
        self.top_bar.set_drive_disconnected()

    # Pipeline start

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

        self.left.set_controls_enabled(False)
        self.center.show_cancel_button(True)
        self.right.clear_models()   # emits cleared -> _on_viewer_cleared -> resets _job_name
        self._result_paths = []

        name_no_ext    = os.path.splitext(os.path.basename(self.left.image_path))[0]
        self._job_name = f"{name_no_ext}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        self.center.set_all_steps(IDLE)

        # Reset Drive section: keep auth state but clear upload affordance
        if self._drive_creds:
            self.center.set_drive_state("connected")
        else:
            self.center.set_drive_state("connect")

        if self.run_mode == "local":
            self._run_local(settings)
        else:
            self._run_cloud(**settings)

    # Cancel

    def _cancel_pipeline(self):
        in_queue = self._queue_timer.isActive()
        prompt = (
            "Leave the queue?\n\nYour uploaded image will be removed and you'll lose your position."
            if in_queue else
            "Cancel the running pipeline?\n\nCloud jobs will be stopped and resources cleaned up."
        )
        reply = QMessageBox.question(
            self,
            "Leave Queue" if in_queue else "Cancel Pipeline",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._log("[CANCEL] Cancelling...", NEON_ORANGE)

        # If still waiting in queue - just dequeue and clean up
        if in_queue:
            self._queue_timer.stop()
            if self._job_queue:
                self._job_queue.dequeue(self._queue_entry_id)
            self._cleanup_gcs_inputs()
            self.center.show_cancel_button(False)
            self.center.set_cancel_label("Cancel Job")
            self.center.set_all_steps(ERROR)
            self._on_pipeline_done(success=False)
            return

        if self.run_mode == "remote":
            self._poll_timer.stop()
            if self._vertex_job:
                try:
                    self._vertex_job.cancel()
                    self._log("[CANCEL] Vertex AI job cancel requested.", NEON_ORANGE)
                except Exception as e:
                    self._log(f"[CANCEL] Could not cancel remote job: {e}", NEON_ORANGE)
            if self._holds_lock and self._job_queue:
                self._job_queue.release_lock()
                self._holds_lock = False
            QTimer.singleShot(3_000, self._cleanup_gcs_inputs)

        elif self.run_mode == "local":
            if self._docker_run_worker:
                self._docker_run_worker.cancel()
            if self._docker_build_worker:
                self._docker_build_worker.cancel()

        self.center.show_cancel_button(False)
        self.center.set_cancel_label("Cancel Job")
        self.center.set_all_steps(ERROR)
        self._on_pipeline_done(success=False)

    # Local - Docker

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
            self._log("[LOCAL] Docker image build/check failed.", NEON_ORANGE)
            self.notification.emit(
                "Neural Forge - Local",
                "Docker image build failed. Check the log for details."
            )
            self._on_pipeline_done(success=False)
            return

        output_dir = os.path.join(
            os.path.expanduser("~"), "Downloads", "NeuralForge", self._job_name
        )
        self._log(f"[LOCAL] Starting pipeline - output: {output_dir}")
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
            output_dir = os.path.join(
                os.path.expanduser("~"), "Downloads", "NeuralForge", self._job_name
            )
            self._result_paths = self._collect_results(output_dir)
            self._log(f"[OUTPUT] Found {len(self._result_paths)} result file(s).")
        self._on_pipeline_done(success=success)

    # Cloud - Vertex AI

    def _run_cloud(self, restormer_tasks, wonder3d_mode, crop, refine,
                   faces, stages, mesh_optimize, print_mode):
        """
        Phase 1: upload the image and join the queue.
        Actual job submission happens in _submit_vertex_job() once it's our turn.
        """
        try:
            cloud_dir = os.path.abspath(os.path.join(self.base_dir, "..", "..", "cloud"))
            if cloud_dir not in sys.path:
                sys.path.insert(0, cloud_dir)

            manager = self.credentials
            email   = self.user_info.get("email", "unknown")

            if email and email != "unknown":
                manager.set_user_prefix(email)

            # Re-read the GPU state file every run so region is always current,
            # even if manage_gpu.py was run after the app started.
            self._sync_persistent_resource(manager)

            budget  = manager.build_budget_manager(user_email=email)
            summary = budget.summary()
            self._log(
                f"[BUDGET] {email} - spent ${summary['spent_usd']:.2f} / "
                f"${summary['monthly_limit_usd']:.2f} this month"
            )

            # GPU type comes from the active persistent resource; fall back to L4 for on-demand
            gpu_type = manager._persistent_gpu_type if manager._persistent_resource_id else "L4"

            # Pre-flight budget check before uploading anything
            allowed, cost, remaining = budget.can_submit(
                gpu_type, refine, wonder3d_mode, crop=crop
            )
            if not allowed:
                raise RuntimeError(
                    f"Budget exceeded. Estimated cost: ${cost:.4f}, "
                    f"remaining: ${remaining:.4f} / ${summary['monthly_limit_usd']:.2f}"
                )

            self._log("[CLOUD] Uploading image to GCS...")
            self.center.set_job_status("Uploading image...", CYAN)

            cloud_uri = manager.upload_file(self.left.image_path)
            image_uri = manager.setup_artifact_registry()
            self._input_basename = os.path.basename(self.left.image_path)

            # Store all job params - used by _submit_vertex_job when our turn arrives
            self._pending_cloud_params = {
                "image_uri":       image_uri,
                "input_uri":       cloud_uri,
                "crop_size":       crop,
                "refine":          refine,
                "mesh_faces":      faces,
                "mesh_stages":     stages,
                "mesh_optimize":   mesh_optimize,
                "mesh_intermediate": stages > 1,
                "wonder3d_mode":   wonder3d_mode,
                "restormer_tasks": restormer_tasks,
                "budget_manager":  budget,
                "gpu_type":        gpu_type,
            }

            # Join the queue
            from JobQueue import JobQueue
            self._job_queue  = JobQueue(
                manager.creds, manager.bucket_name, manager.project_id, manager._user_prefix
            )
            self._holds_lock = False
            entry_id = self._job_queue.enqueue({"job_name": self._job_name})
            self._queue_entry_id = entry_id

            self._log("[QUEUE] Joined the queue. Checking position...")
            self.center.set_cancel_label("Leave Queue")
            self._queue_timer.start(20_000)
            QTimer.singleShot(500, self._poll_queue)

        except RuntimeError as e:
            msg = str(e)
            if "Budget exceeded" in msg or "monthly_limit" in msg:
                self._log(f"[BUDGET ERROR] {msg}", NEON_ORANGE)
            else:
                self._log(f"[CLOUD ERROR] {msg}", NEON_ORANGE)
            self._on_pipeline_done(success=False)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._log(f"[CLOUD ERROR] {e}", NEON_ORANGE)
            self._on_pipeline_done(success=False)

    def _poll_queue(self):
        """Timer callback: check our position, submit when we're first and slot is free."""
        if not self._job_queue or not self._queue_entry_id:
            return
        try:
            position, total = self._job_queue.my_position(self._queue_entry_id)

            if position == -1:
                self._log("[QUEUE] Queue entry not found - may have been removed.", NEON_ORANGE)
                self._queue_timer.stop()
                self._cleanup_gcs_inputs()
                self._on_pipeline_done(success=False)
                return

            if position == 1 and self._job_queue.is_lock_free():
                # Try to grab the GPU slot atomically
                if self._job_queue.try_acquire_lock(self._queue_entry_id):
                    self._holds_lock = True
                    self._queue_timer.stop()
                    self._job_queue.dequeue(self._queue_entry_id)
                    self._log("[QUEUE] GPU slot acquired! Submitting job...", NEON_GREEN)
                    self.center.set_cancel_label("Cancel Job")
                    self._submit_vertex_job()
                else:
                    # Race: another user got it a millisecond earlier - stay in queue
                    self._log("[QUEUE] Slot taken by another user, polling again...", CYAN)
            else:
                wait_msg = f"Queue position: {position} / {total}"
                self.center.set_job_status(wait_msg, CYAN)
                self._log(f"[QUEUE] {wait_msg} - next check in 20s.")

        except Exception as e:
            self._log(f"[QUEUE ERROR] {e}", NEON_ORANGE)

    def _submit_vertex_job(self):
        """Phase 2: submit the Vertex AI job now that we hold the GPU lock."""
        try:
            p       = self._pending_cloud_params
            manager = self.credentials

            self._vertex_job = manager.launch_vertex_job(
                image_uri=      p["image_uri"],
                input_uri=      p["input_uri"],
                crop_size=      p["crop_size"],
                refine=         p["refine"],
                mesh_faces=     p["mesh_faces"],
                mesh_stages=    p["mesh_stages"],
                mesh_optimize=  p["mesh_optimize"],
                mesh_intermediate= p["mesh_intermediate"],
                wonder3d_mode=  p["wonder3d_mode"],
                restormer_tasks=p["restormer_tasks"],
                gpu_type=       p.get("gpu_type", "L4"),
                budget_manager= p["budget_manager"],
            )

            # Store job name in the lock blob so other clients can see who is running
            job_id = self._vertex_job.resource_name.split("/")[-1]
            self._job_queue.update_lock_job_name(job_id)

            self._log(f"[CLOUD] Job submitted: {job_id}")
            self._log(f"[CLOUD] Results folder: ~/Downloads/NeuralForge/{self._job_name}/")
            if manager._persistent_resource_id:
                self._log(
                    "[CLOUD] GPU cluster is ready. Pulling container image - "
                    "first job takes 2–4 min (image cached after that).", CYAN
                )
                self.center.set_job_status("Pulling container image...", CYAN)
            else:
                self._log("[CLOUD] VM is provisioning - GPU allocation may take 2–5 minutes.", CYAN)
                self.center.set_job_status("Waiting for GPU allocation...", CYAN)
            self.center.set_job_id(self._vertex_job.resource_name)
            self.center.set_all_steps(RUNNING)

            self.notification.emit(
                "Neural Forge - Cloud",
                "Job submitted to GPU. Pipeline is starting..."
            )

            self._poll_fast_ticks   = 0
            self._last_vertex_state = ""
            self._poll_timer.start(10_000)

        except RuntimeError as e:
            msg = str(e)
            if "Budget exceeded" in msg or "monthly_limit" in msg:
                self._log(f"[BUDGET ERROR] {msg}", NEON_ORANGE)
            else:
                self._log(f"[CLOUD ERROR] {msg}", NEON_ORANGE)
            if self._holds_lock:
                self._job_queue.release_lock()
                self._holds_lock = False
            self._cleanup_gcs_inputs()
            self._on_pipeline_done(success=False)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._log(f"[CLOUD ERROR] {e}", NEON_ORANGE)
            if self._holds_lock:
                self._job_queue.release_lock()
                self._holds_lock = False
            self._cleanup_gcs_inputs()
            self._on_pipeline_done(success=False)

    # Budget

    def _refresh_budget(self):
        if not self.credentials:
            return
        email = self.user_info.get("email", "")
        if not email:
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
        self._budget_worker.error.connect(self._on_budget_error)
        self._budget_worker.finished.connect(self._budget_thread.quit)
        self._budget_worker.error.connect(self._budget_thread.quit)

        self._budget_thread.start()

    def _on_budget_fetched(self, summary: dict):
        self.left.set_budget(
            spent=summary["spent_usd"],
            limit=summary["monthly_limit_usd"],
            jobs=summary["jobs_count"],
        )

    def _on_budget_error(self, message: str):
        if "insufficient authentication scopes" in message.lower() or "403" in message:
            self._log(
                "[BUDGET] Session credentials outdated - Sign Out and sign in again to restore access.",
                NEON_ORANGE,
            )
        else:
            self._log(f"[BUDGET] Could not load budget: {message}")

    # Vertex AI adaptive polling

    def _poll_vertex_job(self):
        if not self._vertex_job:
            self._poll_timer.stop()
            return
        try:
            self._vertex_job.refresh()
            state = self._vertex_job.state.name

            if state != self._last_vertex_state:
                label, color = _VERTEX_STATE_LABELS.get(state, (f"State: {state}", CYAN))
                self._log(f"[CLOUD] {label}")
                self.center.set_job_status(label, color)
                self._last_vertex_state = state

                if state == "JOB_STATE_RUNNING":
                    self._poll_timer.setInterval(30_000)
                    self.notification.emit(
                        "Neural Forge - Cloud",
                        "GPU is running! Pipeline has started."
                    )
            else:
                self._poll_fast_ticks += 1
                elapsed = self._poll_fast_ticks * 10
                if self._poll_fast_ticks <= 18:
                    if self.credentials._persistent_resource_id:
                        self._log(f"[POLL] Pulling container image… ({elapsed}s)")
                    else:
                        self._log(f"[POLL] Waiting for VM… ({elapsed}s)")
                elif self._poll_fast_ticks == 19:
                    self._poll_timer.setInterval(30_000)

            if state == "JOB_STATE_SUCCEEDED":
                self._poll_timer.stop()
                self.center.set_all_steps(DONE)
                self._log("[CLOUD] Job succeeded!", NEON_GREEN)
                self._cleanup_gcs_inputs()
                if self._holds_lock and self._job_queue:
                    self._job_queue.release_lock()
                    self._holds_lock = False
                self._start_gcs_download()
            elif state in VERTEX_DONE_STATES:
                self._poll_timer.stop()
                self.center.set_all_steps(ERROR)
                self._log(f"[CLOUD] Job ended: {state}", NEON_ORANGE)
                err_msg = self._vertex_job.error_message
                if err_msg:
                    self._log(f"[CLOUD] Error detail: {err_msg}", NEON_ORANGE)
                self._cleanup_gcs_inputs()
                if self._holds_lock and self._job_queue:
                    self._job_queue.release_lock()
                    self._holds_lock = False
                self._on_pipeline_done(success=False)

        except Exception as e:
            self._log(f"[POLL ERROR] {e}", NEON_ORANGE)

    # GCS download

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
        QTimer.singleShot(500, self._cleanup_gcs_outputs)
        self._on_pipeline_done(success=True)

    def _on_gcs_download_error(self, msg: str):
        self._log(f"[GCS ERROR] {msg}", NEON_ORANGE)
        self._on_pipeline_done(success=False)

    # GCS cleanup

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

    # Pipeline done

    def _on_pipeline_done(self, success: bool):
        self.left.set_controls_enabled(True)
        self.center.show_cancel_button(False)
        self.center.set_cancel_label("Cancel Job")
        # Clear queue state
        self._job_queue           = None
        self._queue_entry_id      = None
        self._pending_cloud_params = None

        if success:
            self._log("[PIPELINE] Complete!", NEON_GREEN)
            self.center.set_job_status("Completed", NEON_GREEN)

            if self._result_paths:
                self._load_results_into_viewer(self._result_paths)

                if self._drive_creds:
                    self.center.set_drive_state("ready", n_files=len(self._result_paths))
                # If no Drive creds: keep current state (connect or connected)

            self.notification.emit(
                "Neural Forge - Done",
                f"Pipeline complete! {len(self._result_paths)} file(s) saved to Downloads/NeuralForge."
            )
        else:
            self._log("[PIPELINE] Failed or cancelled.", NEON_ORANGE)
            self.center.set_job_status("Failed / Cancelled", NEON_ORANGE)

        if self.run_mode == "remote":
            self._refresh_budget()

    # History

    def _show_history(self):
        if self._history_panel is not None:
            self._history_panel.raise_()
            self._history_panel.activateWindow()
            return
        from ui.components.JobHistoryPanel import JobHistoryPanel
        panel = JobHistoryPanel(parent=self.window())
        panel.load_requested.connect(self._load_results_from_history)
        panel.finished.connect(lambda: setattr(self, "_history_panel", None))
        self._history_panel = panel
        panel.show()

    def _load_results_from_history(self, paths: list):
        self._result_paths = paths

        # Extract job name: find the first path component under ~/Downloads/NeuralForge/
        if paths:
            neuralforge = os.path.normpath(
                os.path.join(os.path.expanduser("~"), "Downloads", "NeuralForge")
            )
            for p in paths:
                norm = os.path.normpath(p)
                if norm.startswith(neuralforge + os.sep):
                    job_name = norm[len(neuralforge) + 1:].split(os.sep)[0]
                    if job_name:
                        self._job_name = job_name
                        break

        self.right.clear_models()
        self._load_results_into_viewer(paths)

        if self._drive_creds:
            self.center.set_drive_state("ready", n_files=len(paths))
        else:
            self.center.set_drive_state("connect")

        self._log(f"[HISTORY] Loaded {len(paths)} file(s) from history.", NEON_GREEN)

    # Viewer helpers

    def _collect_results(self, directory: str) -> list:
        results = []
        for root, _, files in os.walk(directory):
            for f in files:
                if os.path.splitext(f)[1].lower() in _RESULT_EXTS:
                    results.append(os.path.join(root, f))
        return results

    def _load_results_into_viewer(self, paths: list):
        loaded = 0
        for path in paths:
            if os.path.splitext(path)[1].lower() in _VIEWER_EXTS:
                label = _model_label(path)
                self.right.add_model(path, label)
                self._log(f"[VIEWER] Added: {label} ({os.path.basename(path)})")
                loaded += 1
        if loaded == 0:
            self._log("[VIEWER] No 3D models found to display.")

    # Viewer clear

    def _on_viewer_cleared(self):
        self._result_paths = []
        self._job_name     = None
        if self._drive_creds:
            self.center.set_drive_state("connected")
        else:
            self.center.set_drive_state("connect")

    # Drive upload

    def _save_to_drive(self):
        if not self._result_paths:
            self._log("[DRIVE] No result files to upload.", NEON_ORANGE)
            return
        if not self._drive_creds:
            self._log("[DRIVE] Not authenticated - click 'Login to Google Drive' first.", NEON_ORANGE)
            return

        self.center.set_drive_state("uploading")

        job_name = self._job_name or "results"
        self._log(f"[DRIVE] Uploading {len(self._result_paths)} file(s) -> Neural Forge/{job_name}/")

        self._drive_thread = QThread()
        self._drive_worker = DriveWorker(self._drive_creds, self._result_paths, job_name)
        self._drive_worker.moveToThread(self._drive_thread)

        self._drive_thread.started.connect(self._drive_worker.run)
        self._drive_worker.progress.connect(
            lambda fname, pct: self._log(f"[DRIVE] {fname} - {pct}%")
        )
        self._drive_worker.finished.connect(self._on_drive_done)
        self._drive_worker.error.connect(self._on_drive_error)
        self._drive_worker.finished.connect(self._drive_thread.quit)
        self._drive_worker.error.connect(self._drive_thread.quit)

        self._drive_thread.start()

    def _on_drive_done(self, uploaded: list):
        job_name = self._job_name or "results"
        self._log(
            f"[DRIVE] {len(uploaded)} file(s) saved to Neural Forge/{job_name}/",
            NEON_GREEN,
        )
        self.center.set_drive_state("done")
        self.center.set_job_status("Saved to Drive", NEON_GREEN)
        self.notification.emit(
            "Neural Forge - Drive",
            f"Files saved to Google Drive: Neural Forge/{job_name}/"
        )
    def _on_drive_error(self, message: str):
        display = message.strip() if message else "(unknown error - check terminal for traceback)"
        self._log(f"[DRIVE ERROR] {display}", NEON_ORANGE)
        # Revert to ready so the user can retry
        self.center.set_drive_state("ready", n_files=len(self._result_paths))

    # Logging

    def _log(self, message: str, color: str = None):
        self.center.log(message, color)

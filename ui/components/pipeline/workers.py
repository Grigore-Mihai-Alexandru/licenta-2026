import os
import sys
import subprocess
import time

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Drive auth worker (local mode - no CloudManager available)
# ---------------------------------------------------------------------------

class DriveAuthWorker(QObject):
    """
    Loads or creates Google OAuth credentials for Drive access.
    Reuses token.pickle so the user only authenticates once via browser.
    Emits success(creds, email) - email may be empty if unavailable.
    """
    success = Signal(object, str)  # (google.oauth2.credentials.Credentials, email)
    error   = Signal(str)

    # Include identity scopes so we can show the connected email in the UI.
    _SCOPES = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    ]

    def __init__(self, secrets_path: str, token_path: str):
        super().__init__()
        self.secrets_path = secrets_path
        self.token_path   = token_path

    def run(self):
        try:
            import pickle
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow

            creds = None
            if os.path.exists(self.token_path):
                with open(self.token_path, "rb") as fh:
                    creds = pickle.load(fh)

            # Force fresh auth if token is missing any required scope
            if creds and creds.scopes:
                required = {
                    "https://www.googleapis.com/auth/drive.file",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "openid",
                }
                if not required.issubset(creds.scopes):
                    creds = None

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        creds = None

                if not creds:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.secrets_path, self._SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                with open(self.token_path, "wb") as fh:
                    pickle.dump(creds, fh)

            # Try to extract the email so the UI can display it
            email = ""
            try:
                from googleapiclient.discovery import build as _build
                svc   = _build("oauth2", "v2", credentials=creds)
                info  = svc.userinfo().get().execute()
                email = info.get("email", "")
            except Exception:
                pass

            self.success.emit(creds, email)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Cloud workers
# ---------------------------------------------------------------------------

class BudgetFetchWorker(QObject):
    """Fetches the current month's budget summary from GCS (cloud mode only)."""
    finished = Signal(dict)   # emits CloudBudgetManager.summary()
    error    = Signal(str)

    def __init__(self, cloud_manager, user_email: str):
        super().__init__()
        self.cloud_manager = cloud_manager
        self.user_email    = user_email

    def run(self):
        try:
            budget  = self.cloud_manager.build_budget_manager(user_email=self.user_email)
            self.finished.emit(budget.summary())
        except Exception as e:
            self.error.emit(str(e))


class GCSDownloadWorker(QObject):
    """Downloads outputs/ prefix from GCS to a local directory."""
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, cloud_manager, local_dir: str):
        super().__init__()
        self.cloud_manager = cloud_manager
        self.local_dir     = local_dir

    def run(self):
        try:
            paths = self.cloud_manager.download_results_from_gcs(self.local_dir)
            self.finished.emit(paths)
        except Exception as e:
            self.error.emit(str(e))


class DriveWorker(QObject):
    """Uploads result files to 'Photo2Solid/<job_name>/' on Google Drive."""
    progress = Signal(str, int)
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, creds, file_paths: list, job_name: str):
        super().__init__()
        self.creds      = creds
        self.file_paths = file_paths
        self.job_name   = job_name

    def run(self):
        try:
            cloud_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "cloud")
            )
            if cloud_dir not in sys.path:
                sys.path.insert(0, cloud_dir)
            from DriveManager import DriveManager
        except Exception as e:
            msg = str(e).strip()
            self.error.emit(f"Import error: {msg or type(e).__name__}")
            return

        try:
            dm = DriveManager(self.creds)
        except Exception as e:
            import traceback
            traceback.print_exc()
            msg = str(e).strip()
            self.error.emit(f"Drive init failed: {msg or type(e).__name__}")
            return

        try:
            uploaded = dm.upload_results_for_job(
                self.file_paths, self.job_name,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(uploaded)
        except Exception as e:
            import traceback
            traceback.print_exc()
            msg = str(e).strip()
            self.error.emit(f"[{type(e).__name__}] {msg}" if msg else f"[{type(e).__name__}]")


# ---------------------------------------------------------------------------
# Docker workers
# ---------------------------------------------------------------------------

def _stream_process(proc, log_signal):
    """Read stdout line-by-line and emit each line via log_signal."""
    for line in iter(proc.stdout.readline, ""):
        text = line.rstrip()
        if text:
            log_signal.emit(text)
    proc.stdout.close()
    proc.wait()


class DockerBuildWorker(QObject):
    """
    Builds the local Docker image `photo2solid:latest`.
    Skips the build if the image already exists.
    """
    log      = Signal(str)
    finished = Signal(bool)   # success

    LOCAL_IMAGE = "photo2solid:latest"

    def __init__(self, project_dir: str):
        super().__init__()
        self.project_dir = project_dir
        self._proc       = None

    def cancel(self):
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        try:
            # Check if image already exists
            check = subprocess.run(
                ["docker", "image", "inspect", self.LOCAL_IMAGE],
                capture_output=True,
            )
            if check.returncode == 0:
                self.log.emit(f"[DOCKER] Image {self.LOCAL_IMAGE} already exists - skipping build.")
                self.finished.emit(True)
                return

            self.log.emit(f"[DOCKER] Building image {self.LOCAL_IMAGE} (this can take a long time)...")
            self._proc = subprocess.Popen(
                ["docker", "build", "-t", self.LOCAL_IMAGE, "."],
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _stream_process(self._proc, self.log)
            success = self._proc.returncode == 0
            if success:
                self.log.emit("[DOCKER] Build complete.")
            else:
                self.log.emit(f"[DOCKER] Build failed (exit {self._proc.returncode}).")
            self.finished.emit(success)

        except FileNotFoundError:
            self.log.emit("[DOCKER ERROR] Docker not found. Is Docker Desktop running?")
            self.finished.emit(False)
        except Exception as e:
            self.log.emit(f"[DOCKER ERROR] {e}")
            self.finished.emit(False)


class DockerRunWorker(QObject):
    """
    Runs the pipeline inside the `photo2solid:latest` container.
    Parses container stdout to emit step_done(index) as each step finishes.
    """
    log       = Signal(str)
    step_done = Signal(int)   # 0-based step index
    finished  = Signal(bool)  # success

    LOCAL_IMAGE = "photo2solid:latest"

    # Markers from cloud_pipeline.py print statements (index = step_widget index)
    _STEP_MARKERS = {
        "[STEP 0]": 0,   # ESRGAN
        "[STEP 1]": 1,   # Restormer
        "[STEP 2]": 2,   # Wonder3D
        "[STEP 3]": 3,   # Mesh
    }

    def __init__(self, image_path: str, output_dir: str, settings: dict):
        super().__init__()
        self.image_path      = image_path
        self.output_dir      = output_dir
        self.settings        = settings
        self._proc           = None
        self._container_name = f"photo2solid-{int(time.time())}"

    def cancel(self):
        # Kill the container via Docker Engine so it actually stops, not just the CLI process.
        if self._container_name:
            try:
                subprocess.run(
                    ["docker", "kill", self._container_name],
                    capture_output=True,
                )
            except Exception:
                pass
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)

            input_dir      = os.path.dirname(os.path.abspath(self.image_path))
            image_filename = os.path.basename(self.image_path)

            # Docker Desktop on Windows accepts backslash paths, but forward
            # slashes are safer and work on all platforms.
            input_mount  = input_dir.replace("\\", "/")
            output_mount = self.output_dir.replace("\\", "/")

            # Mount the two pipeline scripts from the local project so that
            # any fix to cloud_pipeline.py or upscale_esrgan.py takes effect
            # immediately without rebuilding the Docker image.
            _project = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            _pipeline_script = os.path.join(_project, "cloud", "cloud_pipeline.py").replace("\\", "/")
            _upscale_script  = os.path.join(_project, "assets", "upscale_esrgan.py").replace("\\", "/")

            s = self.settings
            cmd = [
                "docker", "run", "--rm", "--gpus", "all",
                "--name", self._container_name,
                "-e", "PYTHONUNBUFFERED=1",
                "-v", f"{input_mount}:/app/temp_input",
                "-v", f"{output_mount}:/app/outputs",
                "-v", f"{_pipeline_script}:/app/cloud_pipeline.py:ro",
                "-v", f"{_upscale_script}:/app/upscale_esrgan.py:ro",
                self.LOCAL_IMAGE,
                "--input_image",     f"/app/temp_input/{image_filename}",
                "--output_dir",      "/app/outputs",
                "--restormer_tasks", s["restormer_tasks"],
                "--wonder3d_mode",   s["wonder3d_mode"],
                "--crop",            str(s["crop"]),
                "--refine",          str(s["refine"]),
            ]

            if s.get("upscale"):
                cmd.append("--upscale")

            if s.get("mesh_optimize", True):
                cmd += [
                    "--mesh_faces",  str(s["faces"]),
                    "--mesh_stages", str(s["stages"]),
                ]
                if s.get("stages", 1) > 1:
                    cmd.append("--mesh_intermediate")
                if s.get("lod_watertight", False):
                    cmd.append("--mesh_lod_watertight")
                if s.get("print_mode", False):
                    cmd += [
                        "--mesh_print",
                        "--mesh_size",          str(s.get("print_size", 100)),
                        "--mesh_filament_cost", str(s.get("print_filament_cost", 65)),
                        "--mesh_infill",        str(s.get("print_infill", 20) / 100.0),
                    ]
            else:
                cmd.append("--skip_mesh")

            self.log.emit(f"[DOCKER] Running: {' '.join(cmd[:6])} ...")

            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            for line in iter(self._proc.stdout.readline, ""):
                text = line.rstrip()
                if not text:
                    continue
                self.log.emit(text)
                lower = text.lower()
                for marker, idx in self._STEP_MARKERS.items():
                    if marker in text and ("done" in lower or "skip" in lower):
                        self.step_done.emit(idx)
                        break

            self._proc.stdout.close()
            self._proc.wait()
            success = self._proc.returncode == 0
            if not success:
                self.log.emit(f"[DOCKER] Container exited with code {self._proc.returncode}.")
            self.finished.emit(success)

        except FileNotFoundError:
            self.log.emit("[DOCKER ERROR] Docker not found. Is Docker Desktop running?")
            self.finished.emit(False)
        except Exception as e:
            self.log.emit(f"[DOCKER ERROR] {e}")
            self.finished.emit(False)


class CloudDockerWorker(QObject):
    """
    Builds the local image, tags it as the Artifact Registry URI, and pushes it.
    Requires Docker and gcloud CLI to be installed.
    """
    log      = Signal(str)
    finished = Signal(bool)

    LOCAL_IMAGE = "photo2solid:latest"

    def __init__(self, project_dir: str, image_uri: str, region: str):
        super().__init__()
        self.project_dir = project_dir
        self.image_uri   = image_uri
        self.region      = region

    def _run_cmd(self, cmd: list, cwd: str = None) -> bool:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd or self.project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _stream_process(proc, self.log)
        return proc.returncode == 0

    def run(self):
        try:
            # 1. Build local image if it doesn't exist
            check = subprocess.run(
                ["docker", "image", "inspect", self.LOCAL_IMAGE],
                capture_output=True,
            )
            if check.returncode != 0:
                self.log.emit(f"[CLOUD BUILD] Building {self.LOCAL_IMAGE} (takes a long time)...")
                if not self._run_cmd(["docker", "build", "-t", self.LOCAL_IMAGE, "."]):
                    self.log.emit("[CLOUD BUILD] Docker build failed.")
                    self.finished.emit(False)
                    return
                self.log.emit("[CLOUD BUILD] Build complete.")
            else:
                self.log.emit("[CLOUD BUILD] Local image exists, skipping build.")

            # 2. Tag for Artifact Registry
            self.log.emit(f"[CLOUD BUILD] Tagging as {self.image_uri}...")
            if not self._run_cmd(["docker", "tag", self.LOCAL_IMAGE, self.image_uri]):
                self.log.emit("[CLOUD BUILD] Tagging failed.")
                self.finished.emit(False)
                return

            # 3. Configure Docker auth via gcloud
            registry = f"{self.region}-docker.pkg.dev"
            self.log.emit(f"[CLOUD BUILD] Configuring Docker auth for {registry}...")
            self._run_cmd(["gcloud", "auth", "configure-docker", registry, "--quiet"])

            # 4. Push
            self.log.emit(f"[CLOUD BUILD] Pushing {self.image_uri}...")
            if not self._run_cmd(["docker", "push", self.image_uri]):
                self.log.emit("[CLOUD BUILD] Push failed.")
                self.finished.emit(False)
                return

            self.log.emit("[CLOUD BUILD] Image pushed successfully.")
            self.finished.emit(True)

        except FileNotFoundError as e:
            tool = "Docker" if "docker" in str(e) else "gcloud"
            self.log.emit(f"[CLOUD BUILD ERROR] {tool} CLI not found. Is it installed?")
            self.finished.emit(False)
        except Exception as e:
            self.log.emit(f"[CLOUD BUILD ERROR] {e}")
            self.finished.emit(False)

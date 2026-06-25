import hashlib
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request, AuthorizedSession
from googleapiclient.discovery import build
from google.cloud import storage

from CloudBudgetManager import CloudBudgetManager, DEFAULT_MONTHLY_LIMIT_USD


class _JobState:
    """Thin wrapper so callers can do  job.state.name  like the SDK."""
    def __init__(self, name: str):
        self.name = name


class _VertexJob:
    """
    Drop-in replacement for the high-level SDK CustomJob.
    Uses the Vertex AI REST API directly - no staging bucket required.
    """
    def __init__(self, data: dict, session: AuthorizedSession, vertex_region: str):
        self._data    = data
        self._session = session
        self._region  = vertex_region
        self.resource_name = data["name"]

    @property
    def state(self) -> _JobState:
        return _JobState(self._data.get("state", "JOB_STATE_UNSPECIFIED"))

    def refresh(self):
        url  = f"https://{self._region}-aiplatform.googleapis.com/v1/{self.resource_name}"
        resp = self._session.get(url)
        resp.raise_for_status()
        self._data = resp.json()

    @property
    def error_message(self) -> str:
        err = self._data.get("error")
        if not err:
            return ""
        msg     = err.get("message", "")
        details = err.get("details", [])
        for d in details:
            for v in d.get("violations", []):
                desc = v.get("description", "")
                if desc:
                    msg += f" | {desc}"
        return msg

    def cancel(self):
        url = f"https://{self._region}-aiplatform.googleapis.com/v1/{self.resource_name}:cancel"
        try:
            self._session.post(url)
        except Exception:
            pass


class CloudManager:
    def __init__(self, client_secrets_path="client_secrets.json"):
        self.client_secrets = client_secrets_path
        self.scopes = [
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/cloud-billing.readonly",
            "https://www.googleapis.com/auth/devstorage.read_write",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "openid",
        ]
        self.creds                   = None
        self.project_id              = None
        self.bucket_name             = None
        self.region                  = "europe-west3"  # GCS data bucket region
        self.vertex_region           = "us-central1"   # Vertex AI job region (GPU availability)
        self.registry_region         = "europe-west4"  # Artifact Registry region (existing image)
        self._user_prefix            = "shared"        # overridden by set_user_prefix()
        self._persistent_resource_id  = None   # set via use_persistent_resource()
        self._persistent_gpu_type    = "L4"   # matches GPU type of the persistent resource

    def set_user_prefix(self, email: str):
        """Namespace every GCS path per user - prevents collisions when two users upload same filename."""
        self._user_prefix = hashlib.sha256(email.lower().encode()).hexdigest()[:8]

    # -- Auth ------------------------------------------------------------------

    def authenticate(self):
        token_path = os.path.join(os.path.dirname(self.client_secrets), "token.pickle")

        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                self.creds = pickle.load(f)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    print("Refreshing token...")
                    self.creds.refresh(Request())
                except Exception:
                    self.creds = None

            if not self.creds:
                if not os.path.exists(self.client_secrets):
                    raise FileNotFoundError(f"Missing {self.client_secrets}")
                print("Opening browser for authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets, self.scopes
                )
                self.creds = flow.run_local_server(port=0)

            with open(token_path, "wb") as f:
                pickle.dump(self.creds, f)

        print("Authentication successful.")
        return self.creds

    # -- User info -------------------------------------------------------------

    def get_user_info(self) -> dict:
        try:
            service  = build("oauth2", "v2", credentials=self.creds)
            userinfo = service.userinfo().get().execute()
            return {
                "email":   userinfo.get("email", ""),
                "name":    userinfo.get("name", ""),
                "picture": userinfo.get("picture", ""),
            }
        except Exception as e:
            print(f"Could not fetch user info: {e}")
            return {}

    # -- Project ---------------------------------------------------------------

    def get_project_info(self):
        if not self.creds:
            self.authenticate()

        service  = build("cloudresourcemanager", "v1", credentials=self.creds)
        response = service.projects().list().execute()
        projects = response.get("projects", [])

        if not projects:
            raise RuntimeError("No Google Cloud projects found for this account.")

        self.project_id = projects[0]["projectId"]
        print(f"Using project: {self.project_id}")
        return self.project_id

    # -- Billing ---------------------------------------------------------------

    def check_billing(self):
        if not self.project_id:
            self.get_project_info()
        try:
            billing = build("cloudbilling", "v1", credentials=self.creds)
            info    = billing.projects().getBillingInfo(
                name=f"projects/{self.project_id}"
            ).execute()
            enabled = info.get("billingEnabled", False)
            print(f"Billing {'active' if enabled else 'NOT enabled'} for {self.project_id}.")
            return enabled
        except Exception as e:
            print(f"Error checking billing: {e}")
            return False

    # -- Storage ---------------------------------------------------------------

    def setup_storage(self):
        if not self.project_id:
            self.get_project_info()

        self.bucket_name = f"ai-reconstruction-{self.project_id}"
        client = storage.Client(credentials=self.creds, project=self.project_id)

        try:
            client.get_bucket(self.bucket_name)
            print(f"Bucket exists: {self.bucket_name}")
        except Exception:
            print(f"Creating bucket: {self.bucket_name}...")
            client.create_bucket(self.bucket_name, location=self.region)
            print("Bucket created.")

        return self.bucket_name

    def upload_file(self, local_file_path: str) -> str:
        if not self.bucket_name:
            self.setup_storage()

        client    = storage.Client(credentials=self.creds, project=self.project_id)
        file_name = os.path.basename(local_file_path)
        blob_path = f"inputs/{self._user_prefix}/{file_name}"
        blob      = client.bucket(self.bucket_name).blob(blob_path)

        print(f"Uploading {file_name} to GCS [{self._user_prefix}]...")
        blob.upload_from_filename(local_file_path)

        uri = f"gs://{self.bucket_name}/{blob_path}"
        print(f"Available at: {uri}")
        return uri

    def _gcs_client(self) -> storage.Client:
        return storage.Client(credentials=self.creds, project=self.project_id)

    def download_results_from_gcs(self, local_output_dir: str) -> list[str]:
        if not self.bucket_name:
            raise RuntimeError("Bucket not set. Call setup_storage() first.")

        client     = self._gcs_client()
        bucket     = client.bucket(self.bucket_name)
        prefix     = f"outputs/{self._user_prefix}/"
        blobs      = list(bucket.list_blobs(prefix=prefix))
        os.makedirs(local_output_dir, exist_ok=True)
        downloaded = []

        for blob in blobs:
            # Keep subdirectory structure: strip only the GCS prefix, recreate the rest locally
            rel_path = blob.name[len(prefix):]
            if not rel_path or rel_path.endswith("/"):
                continue  # skip virtual directory blobs
            local_path = os.path.join(local_output_dir, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            print(f"[GCS] Downloading {blob.name} -> {local_path}")
            blob.download_to_filename(local_path)
            downloaded.append(local_path)

        return downloaded

    def delete_gcs_prefix(self, prefix: str):
        if not self.bucket_name:
            return
        client = self._gcs_client()
        blobs  = list(client.bucket(self.bucket_name).list_blobs(prefix=prefix))
        for blob in blobs:
            blob.delete()
            print(f"[GCS] Deleted {blob.name}")
        print(f"[GCS] Deleted {len(blobs)} blob(s) under '{prefix}'")

    def delete_gcs_inputs(self, filename: str = None):
        if filename:
            self.delete_gcs_prefix(f"inputs/{self._user_prefix}/{filename}")
        else:
            self.delete_gcs_prefix(f"inputs/{self._user_prefix}/")

    def delete_gcs_outputs(self):
        self.delete_gcs_prefix(f"outputs/{self._user_prefix}/")

    # -- Budget ----------------------------------------------------------------

    def build_budget_manager(
        self,
        user_email: str,
        monthly_limit: float = DEFAULT_MONTHLY_LIMIT_USD,
    ) -> CloudBudgetManager:
        # Bucket must exist before we can store budget blobs inside it
        if not self.bucket_name:
            self.setup_storage()
        return CloudBudgetManager(
            user_email=user_email,
            creds=self.creds,
            bucket_name=self.bucket_name,
            project_id=self.project_id,
            monthly_limit=monthly_limit,
        )

    # -- Persistent Resource ---------------------------------------------------

    def use_persistent_resource(self, resource_id: str, gpu_type: str = None):
        """Tell the manager to route all future jobs through this persistent resource."""
        if self._persistent_resource_id != resource_id:
            print(f"[GPU] Using persistent resource: {resource_id} ({gpu_type or self._persistent_gpu_type})")
        self._persistent_resource_id = resource_id
        if gpu_type:
            self._persistent_gpu_type = gpu_type.upper()

    def _vertex_base_url(self) -> str:
        return (
            f"https://{self.vertex_region}-aiplatform.googleapis.com/v1"
            f"/projects/{self.project_id}/locations/{self.vertex_region}"
        )

    def create_persistent_resource(self, resource_id: str = "demo-gpu") -> str:
        """
        Provision a persistent L4 GPU cluster in us-central1.
        The cluster stays alive between jobs - jobs start in ~15-30s instead of 2-5 min.
        Takes ~5 minutes to become RUNNING the first time.
        Returns resource_id.
        """
        if not self.project_id:
            self.get_project_info()

        session = AuthorizedSession(self.creds)
        url = f"{self._vertex_base_url()}/persistentResources?persistentResourceId={resource_id}"
        body = {
            "resourcePools": [{
                "machineSpec": {
                    "machineType":      "g2-standard-4",
                    "acceleratorType":  "NVIDIA_L4",
                    "acceleratorCount": 1,
                },
                "replicaCount": "1",
                "diskSpec": {
                    "bootDiskType":   "pd-ssd",
                    "bootDiskSizeGb": 200,
                },
            }]
        }
        resp = session.post(url, json=body)
        if not resp.ok:
            print(f"[GPU] API error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        print(f"[GPU] PersistentResource '{resource_id}' is provisioning (~5 min to become RUNNING).")
        self._persistent_resource_id = resource_id
        return resource_id

    def get_persistent_resource_state(self, resource_id: str = None) -> str:
        """
        Returns the state string of the persistent resource:
        PROVISIONING, RUNNING, STOPPING, STOPPED, ERROR, or NOT_FOUND.
        """
        rid = resource_id or self._persistent_resource_id
        if not rid:
            return "NOT_FOUND"
        if not self.project_id:
            self.get_project_info()
        try:
            session = AuthorizedSession(self.creds)
            url = f"{self._vertex_base_url()}/persistentResources/{rid}"
            resp = session.get(url)
            if resp.status_code == 404:
                return "NOT_FOUND"
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                print(f"[GPU] Resource error detail: {data['error']}")
            return data.get("state", "UNKNOWN")
        except Exception as e:
            print(f"[GPU] Could not get resource state: {e}")
            return "UNKNOWN"

    def delete_persistent_resource(self, resource_id: str = None):
        """
        Shut down and delete the persistent GPU cluster.
        Call this when the demo is done to stop all charges.
        """
        rid = resource_id or self._persistent_resource_id
        if not rid:
            print("[GPU] No persistent resource to delete.")
            return
        if not self.project_id:
            self.get_project_info()
        session = AuthorizedSession(self.creds)
        url = f"{self._vertex_base_url()}/persistentResources/{rid}"
        resp = session.delete(url)
        resp.raise_for_status()
        print(f"[GPU] PersistentResource '{rid}' deletion started. All GPU charges stop once it reaches STOPPED.")
        if rid == self._persistent_resource_id:
            self._persistent_resource_id = None

    # -- Vertex AI job ---------------------------------------------------------

    def launch_vertex_job(
        self,
        image_uri: str,
        input_uri: str,
        crop_size: int = 160,
        refine: int = 0,
        mesh_faces: int = 8000,
        mesh_stages: int = 1,
        mesh_intermediate: bool = False,
        mesh_optimize: bool = True,
        mesh_print: bool = False,
        mesh_lod_watertight: bool = False,
        mesh_size: float = 100.0,
        mesh_filament_cost: float = 65.0,
        mesh_infill: float = 0.20,
        gpu_type: str = "L4",
        wonder3d_mode: str = "official",
        restormer_tasks: str = "Real_Denoising",
        upscale: bool = False,
        budget_manager: CloudBudgetManager = None,
    ):
        gpu_configs = {
            "L4": ("g2-standard-4", "NVIDIA_L4"),
            "T4": ("n1-standard-4", "NVIDIA_TESLA_T4"),
        }
        if gpu_type not in gpu_configs:
            raise ValueError(f"Unknown gpu_type '{gpu_type}'. Choose 'L4' or 'T4'.")

        if budget_manager is not None:
            allowed, cost, remaining = budget_manager.can_submit(
                gpu_type, refine, wonder3d_mode, crop=crop_size,
                upscale=upscale, restormer=bool(restormer_tasks),
            )
            if not allowed:
                summary = budget_manager.summary()
                raise RuntimeError(
                    f"Budget exceeded. Estimated cost: ${cost:.4f}, "
                    f"remaining: ${remaining:.4f} / ${summary['monthly_limit_usd']:.2f} "
                    f"(resets on the 1st of next month)"
                )
            from CloudBudgetManager import estimate_runtime_minutes
            est_min = estimate_runtime_minutes(refine, crop_size, wonder3d_mode, upscale=upscale, restormer=bool(restormer_tasks))
            print(
                f"[BUDGET] Estimated cost: ${cost:.4f} (~{est_min:.1f} min) | "
                f"Remaining after job: ${remaining - cost:.4f}"
            )

        if not self.project_id:
            self.get_project_info()

        machine_type, accelerator_type = gpu_configs[gpu_type]

        args = [
            "--input_image",     input_uri,
            "--output_dir",      f"gs://{self.bucket_name}/outputs/{self._user_prefix}",
            "--crop",            str(crop_size),
            "--refine",          str(refine),
            "--mesh_faces",      str(mesh_faces),
            "--mesh_stages",     str(mesh_stages),
            "--wonder3d_mode",   wonder3d_mode,
            "--restormer_tasks", restormer_tasks,
        ]
        if upscale:
            args.append("--upscale")
        if mesh_intermediate:
            args.append("--mesh_intermediate")
        if mesh_lod_watertight:
            args.append("--mesh_lod_watertight")
        if not mesh_optimize:
            args.append("--skip_mesh")
        if mesh_print:
            args += [
                "--mesh_print",
                "--mesh_size",          str(mesh_size),
                "--mesh_filament_cost", str(mesh_filament_cost),
                "--mesh_infill",        str(mesh_infill),
            ]

        job_spec = {
            "workerPoolSpecs": [{
                "machineSpec": {
                    "machineType":      machine_type,
                    "acceleratorType":  accelerator_type,
                    "acceleratorCount": 1,
                },
                "replicaCount": "1",
                "diskSpec": {
                    "bootDiskType":   "pd-ssd",
                    "bootDiskSizeGb": 200,
                },
                "containerSpec": {
                    "imageUri": image_uri,
                    "args":     args,
                },
            }],
        }
        if self._persistent_resource_id:
            job_spec["persistentResourceId"] = self._persistent_resource_id

        body = {
            "displayName": f"ai_recon_{os.path.basename(input_uri)}",
            "jobSpec": job_spec,
        }

        session = AuthorizedSession(self.creds)
        url = (
            f"https://{self.vertex_region}-aiplatform.googleapis.com/v1"
            f"/projects/{self.project_id}/locations/{self.vertex_region}/customJobs"
        )

        print(f"Submitting Vertex AI job ({gpu_type}, wonder3d={wonder3d_mode}, tasks={restormer_tasks})...")
        resp = session.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        print(f"Job submitted: {data['name']}")

        job = _VertexJob(data, session, self.vertex_region)

        if budget_manager is not None:
            job_name = job.resource_name.split("/")[-1]
            cost     = budget_manager.record_job(gpu_type, refine, job_name, wonder3d_mode, crop=crop_size, upscale=upscale, restormer_tasks=len(restormer_tasks.split(",")) if restormer_tasks else 0)
            print(f"[BUDGET] Recorded ${cost:.4f} for job {job_name}")

        return job

    def get_pipeline_progress(self) -> int:
        """
        Read the latest completed step index from the GCS progress file.
        Returns -1 if the job has not started writing progress yet.
        Never raises — polling failures are silently ignored.
        """
        try:
            import json
            from google.cloud import storage
            client = storage.Client(credentials=self.creds, project=self.project_id)
            blob   = client.bucket(self.bucket_name).blob(
                f"outputs/{self._user_prefix}/progress.json"
            )
            return int(json.loads(blob.download_as_text()).get("step", -1))
        except Exception:
            return -1

    # -- Artifact registry -----------------------------------------------------

    def setup_artifact_registry(self, repo_name: str = "ai-models") -> str:
        if not self.project_id:
            self.get_project_info()

        service = build("artifactregistry", "v1", credentials=self.creds)
        parent  = f"projects/{self.project_id}/locations/{self.registry_region}"
        repo_id = f"{parent}/repositories/{repo_name}"

        try:
            service.projects().locations().repositories().get(name=repo_id).execute()
            print(f"Repository '{repo_name}' exists.")
        except Exception:
            print(f"Creating repository '{repo_name}'...")
            service.projects().locations().repositories().create(
                parent=parent,
                repositoryId=repo_name,
                body={"format": "DOCKER", "description": "AI pipeline models"},
            ).execute()
            print("Repository created.")

        return f"{self.registry_region}-docker.pkg.dev/{self.project_id}/{repo_name}/ai-pipeline:v1"


if __name__ == "__main__":
    manager = CloudManager(
        client_secrets_path=os.path.join(os.path.dirname(__file__), "client_secrets.json")
    )
    manager.authenticate()

    user = manager.get_user_info()
    print(f"Logged in as: {user.get('name')} ({user.get('email')})")

    if manager.check_billing():
        manager.setup_storage()
        test_image = os.path.join(os.path.dirname(__file__), "..", "imgs", "fig.png")
        if os.path.exists(test_image):
            cloud_uri = manager.upload_file(test_image)
            image_uri = manager.setup_artifact_registry()

            budget = manager.build_budget_manager(user_email=user.get("email", ""))
            job = manager.launch_vertex_job(
                image_uri=image_uri,
                input_uri=cloud_uri,
                crop_size=160,
                refine=0,
                mesh_faces=8000,
                mesh_stages=3,
                gpu_type="L4",
                budget_manager=budget,
            )
            print(f"Job started: {job.resource_name}")
        else:
            print(f"Test image not found: {test_image}")
    else:
        print("Enable billing in Google Cloud Console first.")
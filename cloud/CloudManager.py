import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.cloud import storage
from google.cloud import aiplatform


class CloudManager:
    def __init__(self, client_secrets_path="client_secrets.json"):
        self.client_secrets = client_secrets_path
        self.scopes = [
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/cloud-billing.readonly",
            "https://www.googleapis.com/auth/devstorage.read_write",
            "https://www.googleapis.com/auth/drive.file",  # Neural Forge folder only
        ]
        self.creds       = None
        self.project_id  = None
        self.bucket_name = None
        self.region      = "europe-west4"

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

    def get_user_info(self) -> dict:
        # Returns basic profile info using the authenticated credentials
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
        blob      = client.bucket(self.bucket_name).blob(f"inputs/{file_name}")

        print(f"Uploading {file_name} to GCS...")
        blob.upload_from_filename(local_file_path)

        uri = f"gs://{self.bucket_name}/inputs/{file_name}"
        print(f"Available at: {uri}")
        return uri

    def download_results_from_gcs(self, local_output_dir: str) -> list[str]:
        # Downloads all files from outputs/ in the bucket to local dir
        if not self.bucket_name:
            raise RuntimeError("Bucket not set — call setup_storage() first.")

        client    = storage.Client(credentials=self.creds, project=self.project_id)
        bucket    = client.bucket(self.bucket_name)
        blobs     = list(bucket.list_blobs(prefix="outputs/"))
        os.makedirs(local_output_dir, exist_ok=True)
        downloaded = []

        for blob in blobs:
            file_name  = os.path.basename(blob.name)
            if not file_name:
                continue
            local_path = os.path.join(local_output_dir, file_name)
            print(f"[GCS] Downloading {blob.name} → {local_path}")
            blob.download_to_filename(local_path)
            downloaded.append(local_path)

        return downloaded

    def launch_vertex_job(
        self,
        image_uri: str,
        input_uri: str,
        crop_size: int = 160,
        refine: int = 0,
        mesh_faces: int = 8000,
        mesh_stages: int = 1,
        mesh_intermediate: bool = False,
        gpu_type: str = "L4",
        wonder3d_mode: str = "official",
        restormer_tasks: str = "Real_Denoising",
    ):
        gpu_configs = {
            "L4": ("g2-standard-4", "NVIDIA_L4"),
            "T4": ("n1-standard-4", "NVIDIA_TESLA_T4"),
        }
        if gpu_type not in gpu_configs:
            raise ValueError(f"Unknown gpu_type '{gpu_type}'. Choose 'L4' or 'T4'.")

        if not self.project_id:
            self.get_project_info()

        aiplatform.init(
            project=self.project_id,
            location=self.region,
            credentials=self.creds,
        )

        args = [
            "--input_image",     input_uri,
            "--output_dir",      f"gs://{self.bucket_name}/outputs",
            "--crop",            str(crop_size),
            "--refine",          str(refine),
            "--mesh_faces",      str(mesh_faces),
            "--mesh_stages",     str(mesh_stages),
            "--wonder3d_mode",   wonder3d_mode,
            "--restormer_tasks", restormer_tasks,
        ]
        if mesh_intermediate:
            args.append("--mesh_intermediate")

        machine_type, accelerator_type = gpu_configs[gpu_type]

        worker_pool_specs = [{
            "machine_spec": {
                "machine_type":      machine_type,
                "accelerator_type":  accelerator_type,
                "accelerator_count": 1,
            },
            "replica_count": 1,
            "container_spec": {"image_uri": image_uri, "args": args},
        }]

        print(f"Submitting Vertex AI job ({gpu_type}, wonder3d={wonder3d_mode}, tasks={restormer_tasks})...")
        job = aiplatform.CustomJob(
            display_name=f"ai_recon_{os.path.basename(input_uri)}",
            worker_pool_specs=worker_pool_specs,
            staging_bucket=f"gs://{self.bucket_name}/staging",
        )
        job.run(sync=False)
        print(f"Job submitted: {job.resource_name}")
        return job

    def setup_artifact_registry(self, repo_name: str = "ai-models") -> str:
        if not self.project_id:
            self.get_project_info()

        service  = build("artifactregistry", "v1", credentials=self.creds)
        parent   = f"projects/{self.project_id}/locations/{self.region}"
        repo_id  = f"{parent}/repositories/{repo_name}"

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

        return f"{self.region}-docker.pkg.dev/{self.project_id}/{repo_name}/ai-pipeline:v1"


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
            job = manager.launch_vertex_job(
                image_uri=image_uri,
                input_uri=cloud_uri,
                crop_size=160,
                refine=0,
                mesh_faces=8000,
                mesh_stages=3,
                gpu_type="L4",
            )
            print(f"Job started: {job.resource_name}")
        else:
            print(f"Test image not found: {test_image}")
    else:
        print("Enable billing in Google Cloud Console first.")
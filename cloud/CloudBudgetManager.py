import json
import time
from datetime import datetime
from google.cloud import storage


# us-central1 on-demand pricing (VM + GPU accelerator)
MACHINE_COST_PER_HOUR = {
    "L4": 1.37,   # g2-standard-4 ($0.67) + NVIDIA L4 ($0.70)
    "T4": 0.54,   # n1-standard-4 ($0.19) + NVIDIA T4 ($0.35)
}

# Base pipeline runtime at crop=160, refine=0, official mode (minutes)
_BASE_MINUTES = 3.0
# Extra minutes per refine step (at base crop)
_REFINE_MINUTES_PER_STEP = 1.0
# Crop scaling exponent - tuned so crop=256 ≈ 2× the time of crop=160
_CROP_EXPONENT = 1.7
# float16 mode shaves ~15% off Wonder3D inference
_FLOAT16_SPEEDUP = 0.85
# Container startup overhead with PersistentResource (seconds -> minutes)
_STARTUP_MINUTES = 1.0

DEFAULT_MONTHLY_LIMIT_USD = 10.0


def estimate_runtime_minutes(
    refine: int,
    crop: int = 160,
    wonder3d_mode: str = "official",
) -> float:
    """Return estimated wall-clock minutes for the pipeline steps."""
    crop_factor = (crop / 160) ** _CROP_EXPONENT
    pipeline_minutes = (_BASE_MINUTES + refine * _REFINE_MINUTES_PER_STEP) * crop_factor
    if wonder3d_mode == "float16":
        pipeline_minutes *= _FLOAT16_SPEEDUP
    return round(_STARTUP_MINUTES + pipeline_minutes, 2)


class CloudBudgetManager:
    """
    Per-user monthly budget tracker backed by a JSON file in GCS.

    Each user gets one blob at:
        gs://<bucket>/budgets/<safe_email>.json

    The blob is loaded once at construction and written back after
    every recorded job so the data is always up to date across
    multiple app sessions or machines.
    """

    def __init__(
        self,
        user_email: str,
        creds,
        bucket_name: str,
        project_id: str = None,
        monthly_limit: float = DEFAULT_MONTHLY_LIMIT_USD,
    ):
        self.user_email = user_email
        self.monthly_limit = monthly_limit
        self._bucket_name = bucket_name
        # project_id must be explicit: OAuth2 user credentials don't embed the
        # project, so storage.Client() would otherwise fall back to ADC and fail.
        self._client = storage.Client(credentials=creds, project=project_id)
        self._blob_path = f"budgets/{self._safe_email()}.json"
        self._state = self._load()

    # -- Helpers ---------------------------------------------------------------

    def _safe_email(self) -> str:
        return self.user_email.replace("@", "_at_").replace(".", "_")

    def _current_month_key(self) -> str:
        return datetime.now().strftime("%Y-%m")

    # -- Persistence -----------------------------------------------------------

    def _load(self) -> dict:
        try:
            blob = self._client.bucket(self._bucket_name).blob(self._blob_path)
            if blob.exists():
                return json.loads(blob.download_as_text())
        except Exception as exc:
            print(f"[BUDGET] Load failed, starting fresh: {exc}")
        return {"jobs": []}

    def _save(self):
        try:
            blob = self._client.bucket(self._bucket_name).blob(self._blob_path)
            blob.upload_from_string(
                json.dumps(self._state, indent=2),
                content_type="application/json",
            )
        except Exception as exc:
            print(f"[BUDGET] Save failed: {exc}")

    # -- Monthly window --------------------------------------------------------

    def _jobs_this_month(self) -> list:
        key = self._current_month_key()
        return [j for j in self._state.get("jobs", []) if j.get("month") == key]

    def spent_this_month(self) -> float:
        return round(sum(j["estimated_cost"] for j in self._jobs_this_month()), 3)

    def remaining(self) -> float:
        return max(0.0, self.monthly_limit - self.spent_this_month())

    def usage_percent(self) -> float:
        if self.monthly_limit <= 0:
            return 100.0
        return round((self.spent_this_month() / self.monthly_limit) * 100, 1)

    # -- Cost estimation -------------------------------------------------------

    def estimate_job_cost(
        self,
        gpu_type: str,
        refine: int,
        crop: int = 160,
        wonder3d_mode: str = "official",
    ) -> float:
        hourly = MACHINE_COST_PER_HOUR.get(gpu_type, 1.37)
        minutes = estimate_runtime_minutes(refine, crop, wonder3d_mode)
        return round(hourly * (minutes / 60.0), 4)

    # -- Gate check ------------------------------------------------------------

    def can_submit(
        self,
        gpu_type: str,
        refine: int,
        wonder3d_mode: str = "official",
        crop: int = 160,
    ) -> tuple[bool, float, float]:
        """
        Returns (allowed, estimated_cost, remaining_budget).
        Call this before launching any cloud job.
        """
        cost = self.estimate_job_cost(gpu_type, refine, crop, wonder3d_mode)
        rem = self.remaining()
        return rem >= cost, cost, rem

    # -- Recording -------------------------------------------------------------

    def record_job(
        self,
        gpu_type: str,
        refine: int,
        job_name: str,
        wonder3d_mode: str = "official",
        crop: int = 160,
    ) -> float:
        """
        Write the job into GCS immediately after submission.
        Returns the estimated cost that was recorded.
        """
        cost = self.estimate_job_cost(gpu_type, refine, crop, wonder3d_mode)
        est_min = estimate_runtime_minutes(refine, crop, wonder3d_mode)
        self._state.setdefault("jobs", []).append(
            {
                "job_name":       job_name,
                "gpu_type":       gpu_type,
                "refine":         refine,
                "crop":           crop,
                "wonder3d_mode":  wonder3d_mode,
                "estimated_cost": cost,
                "estimated_min":  est_min,
                "timestamp":      time.time(),
                "datetime":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "month":          self._current_month_key(),
            }
        )
        self._save()
        print(f"[BUDGET] Recorded ${cost:.4f} (~{est_min:.1f} min) for job '{job_name}'")
        return cost

    # -- Summary for UI --------------------------------------------------------

    def summary(self) -> dict:
        jobs = self._jobs_this_month()
        return {
            "user":             self.user_email,
            "month":            self._current_month_key(),
            "monthly_limit_usd": self.monthly_limit,
            "spent_usd":        self.spent_this_month(),
            "remaining_usd":    self.remaining(),
            "usage_percent":    self.usage_percent(),
            "jobs_count":       len(jobs),
            "jobs":             jobs,
        }

    def refresh(self):
        """Re-download the blob from GCS. Call this before showing the budget UI."""
        self._state = self._load()

"""
GCS-backed FIFO job queue for the Neural Forge GPU pipeline.

Structure inside the bucket:
    queue/entries/<timestamp_ms>_<user_prefix>.json   - one blob per waiting user
    queue/active.json                                  - held by the currently running job
"""
import json
import time
from datetime import datetime
from google.cloud import storage
from google.api_core import exceptions as gcs_exceptions

MAX_LOCK_AGE_SECONDS = 7200  # 2 h - after this a lock is considered stale/crashed


class JobQueue:
    ENTRY_PREFIX = "queue/entries/"
    LOCK_BLOB    = "queue/active.json"

    def __init__(self, creds, bucket_name: str, project_id: str, user_prefix: str):
        self._client      = storage.Client(credentials=creds, project=project_id)
        self._bucket_name = bucket_name
        self._user_prefix = user_prefix
        self._entry_id    = None  # set after enqueue()

    def _bucket(self):
        return self._client.bucket(self._bucket_name)

    # Queue entries

    def enqueue(self, job_params: dict) -> str:
        """Add this user to the queue. Returns entry_id."""
        ts       = int(time.time() * 1000)
        entry_id = f"{ts:015d}_{self._user_prefix}"
        entry = {
            "entry_id":    entry_id,
            "user_prefix": self._user_prefix,
            "params":      job_params,
            "enqueued_at": time.time(),
            "datetime":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._bucket().blob(f"{self.ENTRY_PREFIX}{entry_id}.json").upload_from_string(
            json.dumps(entry), content_type="application/json"
        )
        self._entry_id = entry_id
        print(f"[QUEUE] Enqueued as '{entry_id}'")
        return entry_id

    def dequeue(self, entry_id: str = None):
        """Remove this user from the queue (called on cancel or when lock acquired)."""
        eid = entry_id or self._entry_id
        if not eid:
            return
        try:
            self._bucket().blob(f"{self.ENTRY_PREFIX}{eid}.json").delete()
            print(f"[QUEUE] Dequeued '{eid}'")
        except Exception:
            pass
        if eid == self._entry_id:
            self._entry_id = None

    def get_queue(self) -> list[dict]:
        """Return all waiting entries sorted oldest-first (by blob name = timestamp)."""
        blobs = sorted(
            self._bucket().list_blobs(prefix=self.ENTRY_PREFIX),
            key=lambda b: b.name,
        )
        entries = []
        for blob in blobs:
            try:
                entries.append(json.loads(blob.download_as_text()))
            except Exception:
                pass
        return entries

    def my_position(self, entry_id: str = None) -> tuple[int, int]:
        """
        Returns (position, total).
        position=1 means front of queue (your turn next).
        position=-1 means your entry is not found.
        """
        eid     = entry_id or self._entry_id
        entries = self.get_queue()
        total   = len(entries)
        for i, e in enumerate(entries):
            if e["entry_id"] == eid:
                return i + 1, total
        return -1, total

    # Lock (the active GPU slot)

    def is_lock_free(self) -> bool:
        """True if no job is currently holding the GPU slot."""
        blob = self._bucket().blob(self.LOCK_BLOB)
        if not blob.exists():
            return True
        # Auto-release locks that are older than MAX_LOCK_AGE_SECONDS
        # (covers the case where the app crashed while holding the lock)
        try:
            data = json.loads(blob.download_as_text())
            age  = time.time() - data.get("acquired_at", 0)
            if age > MAX_LOCK_AGE_SECONDS:
                print(f"[QUEUE] Stale lock ({age/3600:.1f}h old). Auto-releasing.")
                blob.delete()
                return True
        except Exception:
            pass
        return False

    def try_acquire_lock(self, entry_id: str = None) -> bool:
        """
        Atomically acquire the GPU slot using GCS generation-match precondition.
        Returns True if this client won the slot, False if another client got it first.
        """
        eid  = entry_id or self._entry_id
        blob = self._bucket().blob(self.LOCK_BLOB)
        data = {
            "entry_id":    eid,
            "user_prefix": self._user_prefix,
            "job_name":    "",
            "acquired_at": time.time(),
        }
        try:
            blob.upload_from_string(
                json.dumps(data),
                content_type="application/json",
                if_generation_match=0,  # atomic: only succeeds if blob does not exist
            )
            print("[QUEUE] Lock acquired.")
            return True
        except gcs_exceptions.PreconditionFailed:
            print("[QUEUE] Lock taken by another user.")
            return False

    def update_lock_job_name(self, job_name: str):
        """Store the Vertex AI job name in the lock blob after submission."""
        try:
            blob = self._bucket().blob(self.LOCK_BLOB)
            data = json.loads(blob.download_as_text())
            data["job_name"] = job_name
            blob.upload_from_string(json.dumps(data), content_type="application/json")
        except Exception as e:
            print(f"[QUEUE] Could not update lock job_name: {e}")

    def release_lock(self):
        """Release the GPU slot. Call when the job finishes or is cancelled."""
        try:
            self._bucket().blob(self.LOCK_BLOB).delete()
            print("[QUEUE] Lock released.")
        except Exception:
            pass

    def lock_info(self) -> dict:
        """Return current lock data, or {} if slot is free."""
        try:
            blob = self._bucket().blob(self.LOCK_BLOB)
            if blob.exists():
                return json.loads(blob.download_as_text())
        except Exception:
            pass
        return {}

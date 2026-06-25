# DriveManager.py - Google Drive integration: upload results + download to PC

import os
import io
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

FOLDER_NAME = "Photo2Solid"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveManager:
    def __init__(self, creds):
        self.creds   = creds
        self.service = build("drive", "v3", credentials=creds)
        self._folder_id = None

    # Folder

    def get_or_create_folder(self) -> str:
        if self._folder_id:
            return self._folder_id

        query = (
            f"name='{FOLDER_NAME}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        results = self.service.files().list(
            q=query, spaces="drive", fields="files(id, name)"
        ).execute()
        files = results.get("files", [])

        if files:
            self._folder_id = files[0]["id"]
            print(f"[DRIVE] Using existing folder '{FOLDER_NAME}' ({self._folder_id})")
        else:
            metadata = {
                "name":     FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            }
            folder = self.service.files().create(
                body=metadata, fields="id"
            ).execute()
            self._folder_id = folder["id"]
            print(f"[DRIVE] Created folder '{FOLDER_NAME}' ({self._folder_id})")

        return self._folder_id

    def get_or_create_job_folder(self, job_name: str) -> str:
        """Get or create 'Photo2Solid/<job_name>/' and return its Drive folder id."""
        parent_id = self.get_or_create_folder()

        query = (
            f"name='{job_name}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents "
            f"and trashed=false"
        )
        results = self.service.files().list(
            q=query, spaces="drive", fields="files(id, name)"
        ).execute()
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
            print(f"[DRIVE] Using existing job folder '{job_name}' ({folder_id})")
        else:
            metadata = {
                "name":     job_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents":  [parent_id],
            }
            folder = self.service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]
            print(f"[DRIVE] Created job folder '{job_name}' ({folder_id})")

        return folder_id

    # Upload

    def upload_file(self, local_path: str, folder_id: str = None,
                    progress_callback=None) -> dict:
        if folder_id is None:
            folder_id = self.get_or_create_folder()
        file_name = os.path.basename(local_path)
        mime_type = _mime_for(local_path)
        metadata  = {"name": file_name, "parents": [folder_id]}

        print(f"[DRIVE] Uploading {file_name}...")

        for session_attempt in range(1, 6):
            # Fresh MediaFileUpload + request each session attempt (required for 410 restart)
            media   = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
            request = self.service.files().create(
                body=metadata, media_body=media,
                fields="id, name, webViewLink, size"
            )

            response      = None
            chunk_retries = 0
            session_ok    = True

            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status and progress_callback:
                        progress_callback(file_name, int(status.progress() * 100))
                    chunk_retries = 0
                except HttpError as e:
                    if e.resp.status == 410:
                        # Session expired - must restart with a new session URI
                        wait = 2 ** session_attempt
                        print(f"[DRIVE] Session expired (410), restarting upload in {wait}s… "
                              f"(attempt {session_attempt}/5)")
                        time.sleep(wait)
                        session_ok = False
                        break
                    elif e.resp.status in (500, 502, 503, 504) and chunk_retries < 4:
                        chunk_retries += 1
                        wait = 2 ** chunk_retries
                        print(f"[DRIVE] Transient {e.resp.status}, retry {chunk_retries}/4 in {wait}s…")
                        time.sleep(wait)
                    else:
                        raise

            if session_ok and response is not None:
                print(f"   {file_name} -> {response.get('webViewLink', '')}")
                return response

        raise RuntimeError(f"Upload failed after 5 session attempts: {file_name}")

    def upload_results(self, file_paths: list[str], progress_callback=None) -> list[dict]:
        uploaded = []
        for path in file_paths:
            if path and os.path.exists(path):
                info = self.upload_file(path, progress_callback=progress_callback)
                uploaded.append(info)
            else:
                print(f"[DRIVE] Skipped (not found): {path}")
        return uploaded

    def upload_results_for_job(self, file_paths: list[str], job_name: str,
                               progress_callback=None) -> list[dict]:
        """Upload all result files into 'Photo2Solid/<job_name>/' preserving subdirectory structure."""
        job_folder_id = self.get_or_create_job_folder(job_name)

        valid_paths = [p for p in file_paths if p and os.path.exists(p)]
        if not valid_paths:
            return []

        # Derive the local job root so relative paths can be computed
        base_dir = os.path.commonpath(valid_paths)
        if not os.path.isdir(base_dir):
            base_dir = os.path.dirname(base_dir)

        folder_id_cache: dict[str, str] = {}
        uploaded = []

        for path in valid_paths:
            rel  = os.path.relpath(path, base_dir)
            rel_dir = os.path.dirname(rel)

            if rel_dir and rel_dir != ".":
                if rel_dir not in folder_id_cache:
                    folder_id_cache[rel_dir] = self._get_or_create_path(job_folder_id, rel_dir)
                target_id = folder_id_cache[rel_dir]
            else:
                target_id = job_folder_id

            info = self.upload_file(path, folder_id=target_id,
                                    progress_callback=progress_callback)
            uploaded.append(info)

        return uploaded

    def _get_or_create_path(self, parent_id: str, rel_dir: str) -> str:
        """Create Drive subfolder hierarchy for rel_dir under parent_id. Returns leaf folder ID."""
        current_id = parent_id
        for part in rel_dir.replace("\\", "/").split("/"):
            if part and part != ".":
                current_id = self._get_or_create_subfolder(current_id, part)
        return current_id

    def _get_or_create_subfolder(self, parent_id: str, name: str) -> str:
        query = (
            f"name='{name}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents "
            f"and trashed=false"
        )
        results = self.service.files().list(
            q=query, spaces="drive", fields="files(id)"
        ).execute()
        files = results.get("files", [])
        if files:
            return files[0]["id"]
        folder = self.service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder",
                  "parents": [parent_id]},
            fields="id",
        ).execute()
        return folder["id"]

    # Download

    def download_file(self, file_id: str, dest_path: str, progress_callback=None):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        request = self.service.files().get_media(fileId=file_id)

        with io.FileIO(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status and progress_callback:
                    progress_callback(os.path.basename(dest_path), int(status.progress() * 100))

        print(f"[DRIVE] Downloaded -> {dest_path}")
        return dest_path

    def download_results(
        self,
        uploaded: list[dict],
        local_output_dir: str,
        progress_callback=None,
    ) -> list[str]:
        downloaded = []
        os.makedirs(local_output_dir, exist_ok=True)
        for file_info in uploaded:
            file_id   = file_info["id"]
            file_name = file_info["name"]
            dest      = os.path.join(local_output_dir, file_name)
            self.download_file(file_id, dest, progress_callback=progress_callback)
            downloaded.append(dest)
        return downloaded

    # Convenience: full round-trip

    def save_and_download(
        self,
        file_paths: list[str],
        local_output_dir: str,
        progress_callback=None,
    ) -> list[str]:
        uploaded   = self.upload_results(file_paths, progress_callback=progress_callback)
        downloaded = self.download_results(uploaded, local_output_dir, progress_callback=progress_callback)
        return downloaded

    # Folder links (for UI "View in Drive" button)

    def get_folder_link(self) -> str:
        folder_id = self.get_or_create_folder()
        return f"https://drive.google.com/drive/folders/{folder_id}"

    def get_job_folder_link(self, job_name: str) -> str:
        folder_id = self.get_or_create_job_folder(job_name)
        return f"https://drive.google.com/drive/folders/{folder_id}"


# Helpers

def _mime_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".glb":  "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".obj":  "text/plain",
        ".stl":  "application/octet-stream",
        ".json": "application/json",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
    }.get(ext, "application/octet-stream")
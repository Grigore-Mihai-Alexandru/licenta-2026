# DriveManager.py — Google Drive integration: upload results + download to PC

import os
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

FOLDER_NAME = "Neural Forge"
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
        """Get or create 'Neural Forge/<job_name>/' and return its Drive folder id."""
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

        metadata = {"name": file_name, "parents": [folder_id]}
        media    = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

        request  = self.service.files().create(
            body=metadata, media_body=media,
            fields="id, name, webViewLink, size"
        )

        print(f"[DRIVE] Uploading {file_name}...")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(file_name, int(status.progress() * 100))

        print(f"   {file_name} → {response.get('webViewLink', '')}")
        return response

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
        """Upload all result files into 'Neural Forge/<job_name>/'."""
        folder_id = self.get_or_create_job_folder(job_name)
        uploaded = []
        for path in file_paths:
            if path and os.path.exists(path):
                info = self.upload_file(path, folder_id=folder_id,
                                        progress_callback=progress_callback)
                uploaded.append(info)
            else:
                print(f"[DRIVE] Skipped (not found): {path}")
        return uploaded

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

        print(f"[DRIVE] Downloaded → {dest_path}")
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
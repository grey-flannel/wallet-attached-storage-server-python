"""Google Drive storage backend for WAS spaces and resources."""

from __future__ import annotations

import json
import urllib.parse

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from was_server._storage import StoredResource, StoredSpace


class GoogleDriveStorage:
    """Storage backend that persists spaces and resources to Google Drive.

    Uses a service account for authentication. The folder layout mirrors
    the filesystem backend::

        {root_folder}/spaces/{space_uuid}/_meta.json
        {root_folder}/spaces/{space_uuid}/resources/{encoded_path}.data
        {root_folder}/spaces/{space_uuid}/resources/{encoded_path}.meta
    """

    _FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, credentials_json: str, root_folder: str = "was_data") -> None:
        if "{" not in credentials_json:
            # Looks like a file path — load from disk.
            with open(credentials_json) as fh:  # noqa: S603
                info = json.load(fh)
        else:
            info = json.loads(credentials_json)

        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        self._service = build("drive", "v3", credentials=creds)
        self._folder_cache: dict[tuple[str, str], str] = {}

        # Ensure root and spaces folders exist.
        self._root_id = self._find_or_create_folder("root", root_folder)
        self._spaces_folder_id = self._find_or_create_folder(self._root_id, "spaces")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_or_create_folder(self, parent_id: str, name: str) -> str:
        """Return the ID of a child folder, creating it if necessary."""
        key = (parent_id, name)
        if key in self._folder_cache:
            return self._folder_cache[key]

        q = f"name='{name}' and '{parent_id}' in parents and mimeType='{self._FOLDER_MIME}' and trashed=false"
        resp = self._service.files().list(q=q, fields="files(id)").execute()
        files = resp.get("files", [])
        if files:
            folder_id: str = files[0]["id"]
        else:
            body = {"name": name, "mimeType": self._FOLDER_MIME, "parents": [parent_id]}
            created = self._service.files().create(body=body, fields="id").execute()
            folder_id = created["id"]

        self._folder_cache[key] = folder_id
        return folder_id

    def _find_file(self, parent_id: str, name: str) -> str | None:
        """Return the file ID of a named child, or None."""
        q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
        resp = self._service.files().list(q=q, fields="files(id)").execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def _read_file(self, file_id: str) -> bytes:
        """Download the raw bytes of a file."""
        return self._service.files().get_media(fileId=file_id).execute()

    def _upload_file(self, parent_id: str, name: str, content: bytes, content_type: str) -> str:
        """Create or overwrite a file. Returns the file ID."""
        existing_id = self._find_file(parent_id, name)
        media = MediaInMemoryUpload(content, mimetype=content_type)

        if existing_id is not None:
            updated = (
                self._service.files()
                .update(fileId=existing_id, media_body=media, fields="id")
                .execute()
            )
            return updated["id"]

        body = {"name": name, "parents": [parent_id]}
        created = (
            self._service.files()
            .create(body=body, media_body=media, fields="id")
            .execute()
        )
        return created["id"]

    @staticmethod
    def _encode_path(path: str) -> str:
        return urllib.parse.quote(path, safe="")

    # ------------------------------------------------------------------
    # StorageBackend protocol
    # ------------------------------------------------------------------

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        space_folder_id = self._find_file(self._spaces_folder_id, space_uuid)
        if space_folder_id is None:
            return None
        meta_id = self._find_file(space_folder_id, "_meta.json")
        if meta_id is None:
            return None
        raw = self._read_file(meta_id)
        meta = json.loads(raw)
        return StoredSpace(id=meta["id"], controller=meta["controller"])

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        space_folder_id = self._find_or_create_folder(self._spaces_folder_id, space_uuid)
        meta = json.dumps({"id": space_id, "controller": controller}).encode()
        self._upload_file(space_folder_id, "_meta.json", meta, "application/json")

    def delete_space(self, space_uuid: str) -> bool:
        space_folder_id = self._find_file(self._spaces_folder_id, space_uuid)
        if space_folder_id is None:
            return False
        self._service.files().delete(fileId=space_folder_id).execute()
        # Evict all cached entries whose parent is under this space folder.
        to_remove = [
            k for k in self._folder_cache
            if k[0] == space_folder_id or k == (self._spaces_folder_id, space_uuid)
        ]
        for k in to_remove:
            del self._folder_cache[k]
        return True

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        q = f"'{self._spaces_folder_id}' in parents and mimeType='{self._FOLDER_MIME}' and trashed=false"
        resp = self._service.files().list(q=q, fields="files(id,name)").execute()
        folders = resp.get("files", [])
        result: list[StoredSpace] = []
        for folder in folders:
            meta_id = self._find_file(folder["id"], "_meta.json")
            if meta_id is None:
                continue
            raw = self._read_file(meta_id)
            meta = json.loads(raw)
            if meta.get("controller") == controller:
                result.append(StoredSpace(id=meta["id"], controller=meta["controller"]))
        return result

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        space_folder_id = self._find_file(self._spaces_folder_id, space_uuid)
        if space_folder_id is None:
            return None
        res_folder_id = self._find_file(space_folder_id, "resources")
        if res_folder_id is None:
            return None
        encoded = self._encode_path(path)
        data_id = self._find_file(res_folder_id, f"{encoded}.data")
        meta_id = self._find_file(res_folder_id, f"{encoded}.meta")
        if data_id is None or meta_id is None:
            return None
        content = self._read_file(data_id)
        meta = json.loads(self._read_file(meta_id))
        return StoredResource(content=content, content_type=meta["content_type"])

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        space_folder_id = self._find_file(self._spaces_folder_id, space_uuid)
        if space_folder_id is None:
            raise KeyError(f"Space {space_uuid!r} not found")
        res_folder_id = self._find_or_create_folder(space_folder_id, "resources")
        encoded = self._encode_path(path)
        self._upload_file(res_folder_id, f"{encoded}.data", content, content_type)
        meta_bytes = json.dumps({"content_type": content_type}).encode()
        self._upload_file(res_folder_id, f"{encoded}.meta", meta_bytes, "application/json")

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        space_folder_id = self._find_file(self._spaces_folder_id, space_uuid)
        if space_folder_id is None:
            return False
        res_folder_id = self._find_file(space_folder_id, "resources")
        if res_folder_id is None:
            return False
        encoded = self._encode_path(path)
        data_id = self._find_file(res_folder_id, f"{encoded}.data")
        if data_id is None:
            return False
        self._service.files().delete(fileId=data_id).execute()
        meta_id = self._find_file(res_folder_id, f"{encoded}.meta")
        if meta_id is not None:
            self._service.files().delete(fileId=meta_id).execute()
        return True

"""Dropbox storage backend for WAS spaces and resources."""

from __future__ import annotations

import json
import urllib.parse

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import FolderMetadata, WriteMode

from was_server._storage import StoredResource, StoredSpace


class DropboxStorage:
    """Storage backend that persists spaces and resources to Dropbox.

    Uses the Dropbox Python SDK (API v2) for file operations.

    Layout::

        /{root_folder}/spaces/{space_uuid}/_meta.json
        /{root_folder}/spaces/{space_uuid}/resources/{encoded_path}.data
        /{root_folder}/spaces/{space_uuid}/resources/{encoded_path}.meta

    Authentication supports either a long-lived access token or a refresh token
    with app key/secret for automatic renewal.
    """

    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
        root_folder: str = "was_data",
    ) -> None:
        if refresh_token and app_key:
            self._dbx = dropbox.Dropbox(
                oauth2_refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret or "",
            )
        elif access_token:
            self._dbx = dropbox.Dropbox(oauth2_access_token=access_token)
        else:
            raise ValueError("Either access_token or refresh_token+app_key must be provided")
        self._root = f"/{root_folder}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _space_dir(self, space_uuid: str) -> str:
        return f"{self._root}/spaces/{space_uuid}"

    def _meta_path(self, space_uuid: str) -> str:
        return f"{self._space_dir(space_uuid)}/_meta.json"

    @staticmethod
    def _encode_path(path: str) -> str:
        return urllib.parse.quote(path, safe="")

    def _resource_data_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_dir(space_uuid)}/resources/{self._encode_path(path)}.data"

    def _resource_meta_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_dir(space_uuid)}/resources/{self._encode_path(path)}.meta"

    def _upload(self, path: str, data: bytes) -> None:
        """Upload bytes to a Dropbox path, overwriting if it exists."""
        self._dbx.files_upload(data, path, mode=WriteMode.overwrite)

    def _download(self, path: str) -> bytes | None:
        """Download file content. Returns None if file does not exist."""
        try:
            _, response = self._dbx.files_download(path)
            return response.content
        except ApiError as e:
            if _is_not_found(e):
                return None
            raise

    def _delete(self, path: str) -> bool:
        """Delete a file or folder. Returns False if not found."""
        try:
            self._dbx.files_delete_v2(path)
            return True
        except ApiError as e:
            if _is_not_found(e):
                return False
            raise

    def _exists(self, path: str) -> bool:
        """Check whether a file or folder exists."""
        try:
            self._dbx.files_get_metadata(path)
            return True
        except ApiError as e:
            if _is_not_found(e):
                return False
            raise

    # ------------------------------------------------------------------
    # StorageBackend implementation
    # ------------------------------------------------------------------

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        data = self._download(self._meta_path(space_uuid))
        if data is None:
            return None
        meta = json.loads(data)
        return StoredSpace(id=meta["id"], controller=meta["controller"])

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        meta = {"id": space_id, "controller": controller}
        self._upload(self._meta_path(space_uuid), json.dumps(meta).encode())

    def delete_space(self, space_uuid: str) -> bool:
        return self._delete(self._space_dir(space_uuid))

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        spaces_path = f"{self._root}/spaces"
        try:
            result = self._dbx.files_list_folder(spaces_path)
        except ApiError as e:
            if _is_not_found(e):
                return []
            raise

        entries = list(result.entries)
        while result.has_more:
            result = self._dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)

        spaces: list[StoredSpace] = []
        for entry in entries:
            if not isinstance(entry, FolderMetadata):
                continue
            space_uuid = entry.name
            data = self._download(self._meta_path(space_uuid))
            if data is None:
                continue
            meta = json.loads(data)
            if meta.get("controller") == controller:
                spaces.append(StoredSpace(id=meta["id"], controller=meta["controller"]))
        return spaces

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        content = self._download(self._resource_data_path(space_uuid, path))
        if content is None:
            return None
        meta_data = self._download(self._resource_meta_path(space_uuid, path))
        if meta_data is None:
            return None
        meta = json.loads(meta_data)
        return StoredResource(content=content, content_type=meta["content_type"])

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        if not self._exists(self._meta_path(space_uuid)):
            raise KeyError(f"Space {space_uuid!r} not found")
        self._upload(self._resource_data_path(space_uuid, path), content)
        meta = json.dumps({"content_type": content_type}).encode()
        self._upload(self._resource_meta_path(space_uuid, path), meta)

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        if not self._delete(self._resource_data_path(space_uuid, path)):
            return False
        self._delete(self._resource_meta_path(space_uuid, path))
        return True


def _is_not_found(error: ApiError) -> bool:
    """Check if a Dropbox ApiError represents a not-found condition."""
    # ApiError.error is typically a union type; check for path/not_found patterns
    err = error.error
    if hasattr(err, "is_path") and err.is_path():
        lookup = err.get_path()
        if hasattr(lookup, "is_not_found") and lookup.is_not_found():
            return True
    if hasattr(err, "is_path_lookup") and err.is_path_lookup():
        lookup = err.get_path_lookup()
        if hasattr(lookup, "is_not_found") and lookup.is_not_found():
            return True
    return False

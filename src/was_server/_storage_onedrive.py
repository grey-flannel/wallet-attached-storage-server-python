"""OneDrive storage backend for WAS spaces and resources using Microsoft Graph API."""

from __future__ import annotations

import json
import urllib.parse

import httpx
import msal

from was_server._storage import StoredResource, StoredSpace

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]


class OneDriveStorage:
    """Storage backend that persists spaces and resources to Microsoft OneDrive.

    Uses MSAL client credentials flow for authentication and the Microsoft
    Graph API for file operations.

    Layout::

        {root_folder}/spaces/{space_uuid}/_meta.json
        {root_folder}/spaces/{space_uuid}/resources/{encoded_path}.data
        {root_folder}/spaces/{space_uuid}/resources/{encoded_path}.meta
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        drive_id: str | None = None,
        root_folder: str = "was_data",
    ) -> None:
        self._root_folder = root_folder
        self._drive_id = drive_id
        self._msal_app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        self._client = httpx.Client(timeout=30.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Acquire an access token via MSAL client credentials flow."""
        result = self._msal_app.acquire_token_for_client(scopes=_SCOPES)
        if "access_token" not in result:
            raise RuntimeError(f"Failed to acquire token: {result.get('error_description', result.get('error'))}")
        return result["access_token"]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    @property
    def _drive_path(self) -> str:
        if self._drive_id:
            return f"{_GRAPH_BASE}/drives/{self._drive_id}"
        return f"{_GRAPH_BASE}/me/drive"

    def _item_path(self, path: str) -> str:
        """Build a Graph URL for a file/folder by path."""
        return f"{self._drive_path}/root:/{path}:"

    def _get_file(self, path: str) -> httpx.Response:
        """GET file content by path."""
        url = f"{self._item_path(path)}/content"
        return self._client.get(url, headers=self._headers(), follow_redirects=True)

    def _put_file(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> httpx.Response:
        """PUT file content by path."""
        url = f"{self._item_path(path)}/content"
        headers = {**self._headers(), "Content-Type": content_type}
        return self._client.put(url, headers=headers, content=data)

    def _delete_item(self, path: str) -> httpx.Response:
        """DELETE a file or folder by path."""
        url = self._item_path(path)
        return self._client.delete(url, headers=self._headers())

    def _list_children(self, path: str) -> httpx.Response:
        """List children of a folder by path."""
        url = f"{self._item_path(path)}/children"
        return self._client.get(url, headers=self._headers())

    def _space_path(self, space_uuid: str) -> str:
        return f"{self._root_folder}/spaces/{space_uuid}"

    def _meta_path(self, space_uuid: str) -> str:
        return f"{self._space_path(space_uuid)}/_meta.json"

    @staticmethod
    def _encode_path(path: str) -> str:
        return urllib.parse.quote(path, safe="")

    def _resource_data_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_path(space_uuid)}/resources/{self._encode_path(path)}.data"

    def _resource_meta_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_path(space_uuid)}/resources/{self._encode_path(path)}.meta"

    # ------------------------------------------------------------------
    # StorageBackend implementation
    # ------------------------------------------------------------------

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        resp = self._get_file(self._meta_path(space_uuid))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        meta = resp.json()
        return StoredSpace(id=meta["id"], controller=meta["controller"])

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        meta = {"id": space_id, "controller": controller}
        self._put_file(self._meta_path(space_uuid), json.dumps(meta).encode(), "application/json").raise_for_status()

    def delete_space(self, space_uuid: str) -> bool:
        resp = self._delete_item(self._space_path(space_uuid))
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        resp = self._list_children(f"{self._root_folder}/spaces")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        children = resp.json().get("value", [])

        result: list[StoredSpace] = []
        for child in children:
            if "folder" not in child:
                continue
            space_uuid = child["name"]
            meta_resp = self._get_file(self._meta_path(space_uuid))
            if meta_resp.status_code == 404:
                continue
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            if meta.get("controller") == controller:
                result.append(StoredSpace(id=meta["id"], controller=meta["controller"]))
        return result

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        data_resp = self._get_file(self._resource_data_path(space_uuid, path))
        if data_resp.status_code == 404:
            return None
        data_resp.raise_for_status()

        meta_resp = self._get_file(self._resource_meta_path(space_uuid, path))
        if meta_resp.status_code == 404:
            return None
        meta_resp.raise_for_status()

        meta = meta_resp.json()
        return StoredResource(content=data_resp.content, content_type=meta["content_type"])

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        # Verify space exists by checking _meta.json
        meta_resp = self._get_file(self._meta_path(space_uuid))
        if meta_resp.status_code == 404:
            raise KeyError(f"Space {space_uuid!r} not found")
        meta_resp.raise_for_status()

        self._put_file(self._resource_data_path(space_uuid, path), content).raise_for_status()
        resource_meta = json.dumps({"content_type": content_type}).encode()
        self._put_file(self._resource_meta_path(space_uuid, path), resource_meta, "application/json").raise_for_status()

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        data_resp = self._delete_item(self._resource_data_path(space_uuid, path))
        if data_resp.status_code == 404:
            return False
        data_resp.raise_for_status()

        # Clean up the sidecar meta file
        self._delete_item(self._resource_meta_path(space_uuid, path))
        return True

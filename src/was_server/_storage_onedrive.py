"""OneDrive storage backend for WAS spaces and resources using Microsoft Graph API."""

from __future__ import annotations

import httpx
import msal

from was_server._storage import (
    StoredResource,
    StoredSpace,
    encode_resource_path,
    parse_resource_meta,
    parse_space_meta,
    serialize_resource_meta,
    serialize_space_meta,
)

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

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

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

    def _resource_data_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_path(space_uuid)}/resources/{encode_resource_path(path)}.data"

    def _resource_meta_path(self, space_uuid: str, path: str) -> str:
        return f"{self._space_path(space_uuid)}/resources/{encode_resource_path(path)}.meta"

    # ------------------------------------------------------------------
    # StorageBackend implementation
    # ------------------------------------------------------------------

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        resp = self._get_file(self._meta_path(space_uuid))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return parse_space_meta(resp.content)

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        meta = serialize_space_meta(space_id, controller)
        self._put_file(self._meta_path(space_uuid), meta, "application/json").raise_for_status()

    def delete_space(self, space_uuid: str) -> bool:
        resp = self._delete_item(self._space_path(space_uuid))
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        url: str | None = f"{self._item_path(f'{self._root_folder}/spaces')}/children"
        result: list[StoredSpace] = []
        while url:
            resp = self._client.get(url, headers=self._headers())
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            for child in data.get("value", []):
                if "folder" not in child:
                    continue
                space_uuid = child["name"]
                meta_resp = self._get_file(self._meta_path(space_uuid))
                if meta_resp.status_code == 404:
                    continue
                meta_resp.raise_for_status()
                space = parse_space_meta(meta_resp.content)
                if space.controller == controller:
                    result.append(space)
            url = data.get("@odata.nextLink")
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

        return StoredResource(content=data_resp.content, content_type=parse_resource_meta(meta_resp.content))

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        meta_resp = self._get_file(self._meta_path(space_uuid))
        if meta_resp.status_code == 404:
            raise KeyError(f"Space {space_uuid!r} not found")
        meta_resp.raise_for_status()

        self._put_file(self._resource_data_path(space_uuid, path), content).raise_for_status()
        res_meta = serialize_resource_meta(content_type)
        self._put_file(self._resource_meta_path(space_uuid, path), res_meta, "application/json").raise_for_status()

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        data_resp = self._delete_item(self._resource_data_path(space_uuid, path))
        if data_resp.status_code == 404:
            return False
        data_resp.raise_for_status()

        # Clean up the sidecar meta file
        self._delete_item(self._resource_meta_path(space_uuid, path))
        return True

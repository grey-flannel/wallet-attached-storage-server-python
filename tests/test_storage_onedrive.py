"""Tests for OneDrive storage backend with mocked Graph API responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

msal = pytest.importorskip("msal")

from was_server._storage_onedrive import OneDriveStorage  # noqa: E402

pytestmark = pytest.mark.onedrive

FAKE_TOKEN = "fake-access-token"  # noqa: S105
DRIVE_ID = "test-drive-id"
ROOT = "was_data"
SPACE_UUID = "abc-123"
SPACE_ID = "urn:uuid:abc-123"
CONTROLLER = "did:key:z6Mktest"
GRAPH_BASE = f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}"


def _ok(content: bytes = b"", status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
        resp.content = json.dumps(json_data).encode()
    else:
        try:
            resp.json.return_value = json.loads(content) if content else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            resp.json.side_effect = json.JSONDecodeError("Not JSON", "", 0)
    resp.raise_for_status = MagicMock()
    return resp


def _not_found() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 404
    resp.content = b""
    resp.json.return_value = {"error": {"code": "itemNotFound"}}
    resp.raise_for_status = MagicMock(side_effect=Exception("404 Not Found"))
    return resp


@pytest.fixture()
def storage() -> OneDriveStorage:
    with patch("was_server._storage_onedrive.msal") as mock_msal:
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": FAKE_TOKEN}
        mock_msal.ConfidentialClientApplication.return_value = mock_app
        s = OneDriveStorage(
            client_id="cid",
            client_secret="csecret",  # noqa: S106
            tenant_id="tid",
            drive_id=DRIVE_ID,
            root_folder=ROOT,
        )
    return s


class TestTokenAcquisition:
    def test_get_token_success(self, storage: OneDriveStorage) -> None:
        token = storage._get_token()
        assert token == FAKE_TOKEN

    def test_get_token_failure(self, storage: OneDriveStorage) -> None:
        storage._msal_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "Bad credentials",
        }
        with pytest.raises(RuntimeError, match="Bad credentials"):
            storage._get_token()


class TestDrivePath:
    def test_with_drive_id(self, storage: OneDriveStorage) -> None:
        assert storage._drive_path == f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}"

    def test_without_drive_id(self) -> None:
        with patch("was_server._storage_onedrive.msal") as mock_msal:
            mock_app = MagicMock()
            mock_app.acquire_token_for_client.return_value = {"access_token": FAKE_TOKEN}
            mock_msal.ConfidentialClientApplication.return_value = mock_app
            s = OneDriveStorage(client_id="cid", client_secret="csecret", tenant_id="tid")  # noqa: S106
        assert s._drive_path == "https://graph.microsoft.com/v1.0/me/drive"


class TestSpaceCRUD:
    def test_put_and_get_space(self, storage: OneDriveStorage) -> None:
        meta = {"id": SPACE_ID, "controller": CONTROLLER}
        storage._client = MagicMock()
        storage._client.put.return_value = _ok()
        storage._client.get.return_value = _ok(json_data=meta)

        storage.put_space(SPACE_UUID, SPACE_ID, CONTROLLER)
        space = storage.get_space(SPACE_UUID)

        assert space is not None
        assert space.id == SPACE_ID
        assert space.controller == CONTROLLER

    def test_get_space_not_found(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.get.return_value = _not_found()

        result = storage.get_space(SPACE_UUID)
        assert result is None

    def test_delete_space_success(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.delete.return_value = _ok(status_code=204)

        assert storage.delete_space(SPACE_UUID) is True

    def test_delete_space_not_found(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.delete.return_value = _not_found()

        assert storage.delete_space(SPACE_UUID) is False


class TestListSpaces:
    def test_list_spaces_filters_by_controller(self, storage: OneDriveStorage) -> None:
        children = {
            "value": [
                {"name": "space-1", "folder": {}},
                {"name": "space-2", "folder": {}},
                {"name": "not-a-folder"},  # should be skipped
            ]
        }
        meta_1 = {"id": "urn:uuid:space-1", "controller": CONTROLLER}
        meta_2 = {"id": "urn:uuid:space-2", "controller": "did:key:z6MkOTHER"}

        storage._client = MagicMock()

        def mock_get(url: str, **kwargs: object) -> MagicMock:
            if url.endswith("/children"):
                return _ok(json_data=children)
            if "space-1/_meta.json" in url:
                return _ok(json_data=meta_1)
            if "space-2/_meta.json" in url:
                return _ok(json_data=meta_2)
            return _not_found()

        storage._client.get.side_effect = mock_get

        result = storage.list_spaces(CONTROLLER)
        assert len(result) == 1
        assert result[0].id == "urn:uuid:space-1"
        assert result[0].controller == CONTROLLER

    def test_list_spaces_empty(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.get.return_value = _not_found()

        result = storage.list_spaces(CONTROLLER)
        assert result == []


class TestResourceCRUD:
    def test_put_and_get_resource(self, storage: OneDriveStorage) -> None:
        space_meta = {"id": SPACE_ID, "controller": CONTROLLER}
        resource_content = b"hello world"
        resource_meta = {"content_type": "text/plain"}

        storage._client = MagicMock()
        call_count = 0

        def mock_get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if "_meta.json" in url and "resources" not in url:
                return _ok(json_data=space_meta)
            if url.endswith(".data:/content"):
                return _ok(content=resource_content)
            if url.endswith(".meta:/content"):
                return _ok(json_data=resource_meta)
            return _not_found()

        storage._client.get.side_effect = mock_get
        storage._client.put.return_value = _ok(status_code=201)

        storage.put_resource(SPACE_UUID, "doc/readme.txt", resource_content, "text/plain")
        result = storage.get_resource(SPACE_UUID, "doc/readme.txt")

        assert result is not None
        assert result.content == resource_content
        assert result.content_type == "text/plain"

    def test_get_resource_not_found(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.get.return_value = _not_found()

        result = storage.get_resource(SPACE_UUID, "missing.txt")
        assert result is None

    def test_put_resource_space_not_found(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.get.return_value = _not_found()

        with pytest.raises(KeyError, match="not found"):
            storage.put_resource(SPACE_UUID, "file.txt", b"data", "text/plain")

    def test_delete_resource_success(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.delete.return_value = _ok(status_code=204)

        assert storage.delete_resource(SPACE_UUID, "file.txt") is True

    def test_delete_resource_not_found(self, storage: OneDriveStorage) -> None:
        storage._client = MagicMock()
        storage._client.delete.return_value = _not_found()

        assert storage.delete_resource(SPACE_UUID, "file.txt") is False


class TestPathEncoding:
    def test_resource_paths_are_encoded(self, storage: OneDriveStorage) -> None:
        data_path = storage._resource_data_path(SPACE_UUID, "my file/doc.txt")
        assert "my%20file%2Fdoc.txt.data" in data_path

        meta_path = storage._resource_meta_path(SPACE_UUID, "my file/doc.txt")
        assert "my%20file%2Fdoc.txt.meta" in meta_path

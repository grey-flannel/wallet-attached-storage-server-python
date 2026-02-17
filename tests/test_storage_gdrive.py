"""Google Drive storage backend tests using a fully mocked Drive API."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("googleapiclient")
pytest.importorskip("google.oauth2")

from was_server._storage_gdrive import GoogleDriveStorage  # noqa: E402


# ---------------------------------------------------------------------------
# Mock Drive service that keeps files in a dict
# ---------------------------------------------------------------------------


class _MockDriveFiles:
    """In-memory simulation of the Drive files() resource."""

    def __init__(self) -> None:
        self._files: dict[str, dict] = {}  # id -> {name, parents, mimeType, content}

    def _new_id(self) -> str:
        return f"gdrive-{uuid.uuid4().hex[:8]}"

    # -- files().list() -----------------------------------------------------

    def list(self, *, q: str = "", fields: str = "") -> MagicMock:  # noqa: A003
        result_files: list[dict] = []
        for f in self._files.values():
            if not self._matches_query(f, q):
                continue
            entry: dict = {"id": f["id"]}
            if "name" in fields or fields == "":
                entry["name"] = f["name"]
            result_files.append(entry)
        resp = {"files": result_files}
        req = MagicMock()
        req.execute.return_value = resp
        return req

    @staticmethod
    def _matches_query(f: dict, q: str) -> bool:
        """Minimal query parser — good enough for the storage backend's queries."""
        if not q:
            return True
        parts = [p.strip() for p in q.split(" and ")]
        for part in parts:
            if part == "trashed=false":
                if f.get("trashed"):
                    return False
            elif part.startswith("name='"):
                name_val = part.split("'")[1]
                if f["name"] != name_val:
                    return False
            elif "in parents" in part:
                parent_id = part.split("'")[1]
                if parent_id not in f.get("parents", []):
                    return False
            elif part.startswith("mimeType='"):
                mime_val = part.split("'")[1]
                if f.get("mimeType") != mime_val:
                    return False
        return True

    # -- files().create() ---------------------------------------------------

    def create(self, *, body: dict | None = None, media_body: object | None = None, fields: str = "") -> MagicMock:
        body = body or {}
        file_id = self._new_id()
        entry: dict = {
            "id": file_id,
            "name": body.get("name", "untitled"),
            "mimeType": body.get("mimeType", "application/octet-stream"),
            "parents": body.get("parents", []),
            "trashed": False,
            "content": b"",
        }
        if media_body is not None:
            entry["content"] = self._extract_bytes(media_body)
        self._files[file_id] = entry
        req = MagicMock()
        req.execute.return_value = {"id": file_id}
        return req

    # -- files().update() ---------------------------------------------------

    def update(self, *, fileId: str, media_body: object | None = None, fields: str = "") -> MagicMock:  # noqa: N803
        if fileId in self._files and media_body is not None:
            self._files[fileId]["content"] = self._extract_bytes(media_body)
        req = MagicMock()
        req.execute.return_value = {"id": fileId}
        return req

    # -- files().get_media() ------------------------------------------------

    def get_media(self, *, fileId: str) -> MagicMock:  # noqa: N803
        req = MagicMock()
        f = self._files.get(fileId)
        req.execute.return_value = f["content"] if f else b""
        return req

    # -- files().delete() ---------------------------------------------------

    def delete(self, *, fileId: str) -> MagicMock:  # noqa: N803
        self._files.pop(fileId, None)
        req = MagicMock()
        req.execute.return_value = None
        return req

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _extract_bytes(media: object) -> bytes:
        """Pull raw bytes from a MediaInMemoryUpload or mock."""
        body = getattr(media, "_body", None)
        if isinstance(body, bytes):
            return body
        fd = getattr(media, "_fd", None)
        if fd is not None:
            fd.seek(0)
            return fd.read()
        return b""


class _MockDriveService:
    """Top-level mock for ``googleapiclient.discovery.build(...)``."""

    def __init__(self) -> None:
        self._files_resource = _MockDriveFiles()

    def files(self) -> _MockDriveFiles:
        return self._files_resource


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_SA_INFO = json.dumps({
    "type": "service_account",
    "project_id": "test",
    "private_key_id": "1",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA2Z3qX2BTLS4e+"
                   "XSLGB4BO34RFJAbKaUFmFSaL7OmcFGmmKol"
                   "\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test.iam.gserviceaccount.com",
    "client_id": "1234567890",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
})


@pytest.fixture()
def mock_service() -> _MockDriveService:
    return _MockDriveService()


@pytest.fixture()
def gdrive_store(mock_service: _MockDriveService) -> GoogleDriveStorage:
    """Build a GoogleDriveStorage wired to our mock service."""
    with (
        patch("was_server._storage_gdrive.Credentials.from_service_account_info") as mock_creds_cls,
        patch("was_server._storage_gdrive.build") as mock_build,
    ):
        mock_creds_cls.return_value = MagicMock()
        mock_build.return_value = mock_service
        store = GoogleDriveStorage(credentials_json=FAKE_SA_INFO)
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCredentialLoading:
    def test_inline_json(self, mock_service: _MockDriveService) -> None:
        with (
            patch("was_server._storage_gdrive.Credentials.from_service_account_info") as mock_creds,
            patch("was_server._storage_gdrive.build") as mock_build,
        ):
            mock_creds.return_value = MagicMock()
            mock_build.return_value = mock_service
            GoogleDriveStorage(credentials_json=FAKE_SA_INFO)
            mock_creds.assert_called_once()
            info = mock_creds.call_args[0][0]
            assert info["type"] == "service_account"

    def test_file_path(self, tmp_path: object, mock_service: _MockDriveService) -> None:
        from pathlib import Path

        cred_file = Path(str(tmp_path)) / "sa.json"
        cred_file.write_text(FAKE_SA_INFO)

        with (
            patch("was_server._storage_gdrive.Credentials.from_service_account_info") as mock_creds,
            patch("was_server._storage_gdrive.build") as mock_build,
        ):
            mock_creds.return_value = MagicMock()
            mock_build.return_value = mock_service
            GoogleDriveStorage(credentials_json=str(cred_file))
            mock_creds.assert_called_once()
            info = mock_creds.call_args[0][0]
            assert info["type"] == "service_account"


class TestSpaceCrud:
    def test_put_and_get(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        space = gdrive_store.get_space("abc")
        assert space is not None
        assert space.id == "urn:uuid:abc"
        assert space.controller == "did:key:z1"

    def test_get_nonexistent(self, gdrive_store: GoogleDriveStorage) -> None:
        assert gdrive_store.get_space("missing") is None

    def test_put_updates_controller(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        space = gdrive_store.get_space("abc")
        assert space is not None
        assert space.controller == "did:key:z2"

    def test_delete(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert gdrive_store.delete_space("abc") is True
        assert gdrive_store.get_space("abc") is None

    def test_delete_nonexistent(self, gdrive_store: GoogleDriveStorage) -> None:
        assert gdrive_store.delete_space("missing") is False

    def test_list_by_controller(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("a", "urn:uuid:a", "did:key:z1")
        gdrive_store.put_space("b", "urn:uuid:b", "did:key:z1")
        gdrive_store.put_space("c", "urn:uuid:c", "did:key:z2")
        spaces = gdrive_store.list_spaces("did:key:z1")
        assert len(spaces) == 2
        ids = {s.id for s in spaces}
        assert ids == {"urn:uuid:a", "urn:uuid:b"}


class TestResourceCrud:
    def test_put_and_get(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        gdrive_store.put_resource("abc", "/file.txt", b"hello", "text/plain")
        resource = gdrive_store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"hello"
        assert resource.content_type == "text/plain"

    def test_get_nonexistent_resource(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert gdrive_store.get_resource("abc", "/missing") is None

    def test_get_resource_nonexistent_space(self, gdrive_store: GoogleDriveStorage) -> None:
        assert gdrive_store.get_resource("missing", "/file.txt") is None

    def test_put_resource_nonexistent_space_raises(self, gdrive_store: GoogleDriveStorage) -> None:
        with pytest.raises(KeyError):
            gdrive_store.put_resource("missing", "/file.txt", b"data", "text/plain")

    def test_delete_resource(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        gdrive_store.put_resource("abc", "/file.txt", b"data", "text/plain")
        assert gdrive_store.delete_resource("abc", "/file.txt") is True
        assert gdrive_store.get_resource("abc", "/file.txt") is None

    def test_delete_nonexistent_resource(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert gdrive_store.delete_resource("abc", "/missing") is False

    def test_delete_resource_nonexistent_space(self, gdrive_store: GoogleDriveStorage) -> None:
        assert gdrive_store.delete_resource("missing", "/file.txt") is False

    def test_overwrite_resource(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        gdrive_store.put_resource("abc", "/f.txt", b"v1", "text/plain")
        gdrive_store.put_resource("abc", "/f.txt", b"v2", "application/octet-stream")
        resource = gdrive_store.get_resource("abc", "/f.txt")
        assert resource is not None
        assert resource.content == b"v2"
        assert resource.content_type == "application/octet-stream"


class TestFolderCache:
    def test_folder_created_once(self, gdrive_store: GoogleDriveStorage, mock_service: _MockDriveService) -> None:
        """After creating a space, the folder ID should be cached so subsequent lookups don't create duplicates."""
        gdrive_store.put_space("s1", "urn:uuid:s1", "did:key:z1")

        # Count folders named "s1" under spaces
        spaces_id = gdrive_store._spaces_folder_id
        folder_mime = "application/vnd.google-apps.folder"
        q = f"name='s1' and '{spaces_id}' in parents and mimeType='{folder_mime}' and trashed=false"
        resp = mock_service.files().list(q=q, fields="files(id)").execute()
        assert len(resp["files"]) == 1

        # Call put_space again — should reuse cached folder, not create another.
        gdrive_store.put_space("s1", "urn:uuid:s1", "did:key:z2")
        resp = mock_service.files().list(q=q, fields="files(id)").execute()
        assert len(resp["files"]) == 1

    def test_delete_space_clears_cache(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        assert any(k[1] == "s1" for k in gdrive_store._folder_cache)
        gdrive_store.delete_space("s1")
        assert not any(k[1] == "s1" for k in gdrive_store._folder_cache)


class TestDeleteSpaceCleansResources:
    def test_resources_gone_after_space_delete(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        gdrive_store.put_resource("s1", "/a.txt", b"aaa", "text/plain")
        gdrive_store.put_resource("s1", "/b.txt", b"bbb", "text/plain")
        gdrive_store.delete_space("s1")
        assert gdrive_store.get_space("s1") is None
        assert gdrive_store.get_resource("s1", "/a.txt") is None


class TestPutPreservesResources:
    def test_update_controller_keeps_resources(self, gdrive_store: GoogleDriveStorage) -> None:
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        gdrive_store.put_resource("abc", "/file.txt", b"data", "text/plain")
        gdrive_store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        resource = gdrive_store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"data"

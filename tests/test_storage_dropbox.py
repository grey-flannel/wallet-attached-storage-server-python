"""Tests for the Dropbox storage backend using mocked Dropbox SDK."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

dbx_mod = pytest.importorskip("dropbox")

from dropbox.exceptions import ApiError  # noqa: E402
from dropbox.files import FileMetadata, FolderMetadata  # noqa: E402

from was_server._storage_dropbox import DropboxStorage  # noqa: E402


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockLookupError:
    """Simulates a LookupError with is_not_found()."""

    def is_not_found(self) -> bool:
        return True


class _MockPathError:
    """Simulates an error union with is_path() / get_path()."""

    def is_path(self) -> bool:
        return True

    def get_path(self) -> _MockLookupError:
        return _MockLookupError()

    def is_path_lookup(self) -> bool:
        return False


def _not_found_error() -> ApiError:
    """Create a mock ApiError that represents a not-found condition."""
    return ApiError("req-id", _MockPathError(), "user-message", "user-message-locale")


class _FakeDropboxClient:
    """In-memory simulation of the Dropbox SDK client."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    def files_upload(self, data: bytes, path: str, mode: object = None) -> FileMetadata:
        self._files[path.lower()] = data
        return FileMetadata(name=path.rsplit("/", 1)[-1], path_lower=path.lower(), id="id:fake")

    def files_download(self, path: str) -> tuple[FileMetadata, MagicMock]:
        key = path.lower()
        if key not in self._files:
            raise _not_found_error()
        resp = MagicMock()
        resp.content = self._files[key]
        meta = FileMetadata(name=path.rsplit("/", 1)[-1], path_lower=key, id="id:fake")
        return meta, resp

    def files_delete_v2(self, path: str) -> object:
        key = path.lower()
        # Delete the exact path or everything under it (folder delete)
        deleted = []
        for k in list(self._files):
            if k == key or k.startswith(key + "/"):
                deleted.append(k)
        if not deleted:
            raise _not_found_error()
        for k in deleted:
            del self._files[k]
        return MagicMock()

    def files_get_metadata(self, path: str) -> FileMetadata:
        key = path.lower()
        if key in self._files:
            return FileMetadata(name=path.rsplit("/", 1)[-1], path_lower=key, id="id:fake")
        # Check if it's a "folder" (any file has this as prefix)
        if any(k.startswith(key + "/") for k in self._files):
            return FolderMetadata(name=path.rsplit("/", 1)[-1], path_lower=key, id="id:fake")
        raise _not_found_error()

    def files_list_folder(self, path: str) -> MagicMock:
        prefix = path.lower() + "/"
        # Find direct children (folders at the next level)
        child_names: set[str] = set()
        for k in self._files:
            if k.startswith(prefix):
                relative = k[len(prefix):]
                child_name = relative.split("/")[0]
                child_names.add(child_name)

        if not child_names and not any(k.startswith(prefix) for k in self._files):
            # Folder doesn't exist
            raise _not_found_error()

        entries = []
        for name in sorted(child_names):
            child_path = f"{prefix}{name}"
            # If there are files under this child, it's a folder
            if any(k.startswith(child_path + "/") for k in self._files):
                entries.append(FolderMetadata(name=name, path_lower=child_path, id=f"id:{name}"))
            else:
                entries.append(FileMetadata(name=name, path_lower=child_path, id=f"id:{name}"))

        result = MagicMock()
        result.entries = entries
        result.has_more = False
        return result


@pytest.fixture()
def fake_dbx() -> _FakeDropboxClient:
    return _FakeDropboxClient()


@pytest.fixture()
def store(fake_dbx: _FakeDropboxClient) -> Generator[DropboxStorage]:
    with patch("was_server._storage_dropbox.dropbox.Dropbox", return_value=fake_dbx):
        yield DropboxStorage(access_token="fake-token", root_folder="was_data")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_access_token(self, fake_dbx: _FakeDropboxClient) -> None:
        with patch("was_server._storage_dropbox.dropbox.Dropbox", return_value=fake_dbx) as mock_cls:
            DropboxStorage(access_token="tok123")
            mock_cls.assert_called_once_with(oauth2_access_token="tok123")

    def test_refresh_token(self, fake_dbx: _FakeDropboxClient) -> None:
        with patch("was_server._storage_dropbox.dropbox.Dropbox", return_value=fake_dbx) as mock_cls:
            DropboxStorage(refresh_token="ref123", app_key="key", app_secret="secret")
            mock_cls.assert_called_once_with(oauth2_refresh_token="ref123", app_key="key", app_secret="secret")

    def test_no_credentials_raises(self) -> None:
        with pytest.raises(ValueError, match="Either access_token or refresh_token"):
            DropboxStorage()


class TestSpaceCrud:
    def test_put_and_get(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        space = store.get_space("abc")
        assert space is not None
        assert space.id == "urn:uuid:abc"
        assert space.controller == "did:key:z1"

    def test_get_nonexistent(self, store: DropboxStorage) -> None:
        assert store.get_space("missing") is None

    def test_put_updates_controller(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        space = store.get_space("abc")
        assert space is not None
        assert space.controller == "did:key:z2"

    def test_delete(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_space("abc") is True
        assert store.get_space("abc") is None

    def test_delete_nonexistent(self, store: DropboxStorage) -> None:
        assert store.delete_space("missing") is False

    def test_list_by_controller(self, store: DropboxStorage) -> None:
        store.put_space("a", "urn:uuid:a", "did:key:z1")
        store.put_space("b", "urn:uuid:b", "did:key:z1")
        store.put_space("c", "urn:uuid:c", "did:key:z2")
        spaces = store.list_spaces("did:key:z1")
        assert len(spaces) == 2
        ids = {s.id for s in spaces}
        assert ids == {"urn:uuid:a", "urn:uuid:b"}


class TestResourceCrud:
    def test_put_and_get(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"hello", "text/plain")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"hello"
        assert resource.content_type == "text/plain"

    def test_get_nonexistent_resource(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.get_resource("abc", "/missing") is None

    def test_get_resource_nonexistent_space(self, store: DropboxStorage) -> None:
        assert store.get_resource("missing", "/file.txt") is None

    def test_put_resource_nonexistent_space_raises(self, store: DropboxStorage) -> None:
        with pytest.raises(KeyError):
            store.put_resource("missing", "/file.txt", b"data", "text/plain")

    def test_delete_resource(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        assert store.delete_resource("abc", "/file.txt") is True
        assert store.get_resource("abc", "/file.txt") is None

    def test_delete_nonexistent_resource(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_resource("abc", "/missing") is False

    def test_delete_resource_nonexistent_space(self, store: DropboxStorage) -> None:
        assert store.delete_resource("missing", "/file.txt") is False

    def test_overwrite_resource(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/f.txt", b"v1", "text/plain")
        store.put_resource("abc", "/f.txt", b"v2", "text/html")
        resource = store.get_resource("abc", "/f.txt")
        assert resource is not None
        assert resource.content == b"v2"
        assert resource.content_type == "text/html"


class TestDeleteSpaceCascade:
    def test_resources_gone_after_space_delete(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        store.delete_space("abc")
        assert store.get_resource("abc", "/file.txt") is None

    def test_put_preserves_resources(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"data"


class TestPathEncoding:
    def test_special_chars_in_path(self, store: DropboxStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        path = "/dir/file with spaces & symbols!.txt"
        store.put_resource("abc", path, b"special", "text/plain")
        resource = store.get_resource("abc", path)
        assert resource is not None
        assert resource.content == b"special"

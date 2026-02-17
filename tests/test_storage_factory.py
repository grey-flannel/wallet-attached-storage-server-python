"""Tests for the storage backend factory."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from was_server._storage import MemoryStorage

# Ensure psycopg_pool is importable even when psycopg is not installed.
if "psycopg_pool" not in sys.modules:
    _stub = types.ModuleType("psycopg_pool")
    _stub.ConnectionPool = MagicMock  # type: ignore[attr-defined]
    sys.modules["psycopg_pool"] = _stub


def _create(backend: str, config: dict[str, str] | None = None):
    """Helper: call create_storage() with mocked settings."""
    config = config or {}
    with (
        patch("was_server._storage_factory.get_backend_name", return_value=backend),
        patch("was_server._storage_factory.get_storage_config", return_value=config),
    ):
        from was_server._storage_factory import create_storage

        return create_storage()


class TestMemoryBackend:
    def test_default(self) -> None:
        store = _create("memory")
        assert isinstance(store, MemoryStorage)


class TestFilesystemBackend:
    def test_creates_instance(self, tmp_path) -> None:
        store = _create("filesystem", {"root_dir": str(tmp_path)})
        from was_server._storage_filesystem import FilesystemStorage

        assert isinstance(store, FilesystemStorage)


class TestS3Backend:
    def test_missing_bucket_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_BUCKET"):
            _create("s3")

    def test_creates_instance(self) -> None:
        with patch("was_server._storage_s3.boto3") as mock_boto:
            mock_boto.client.return_value = MagicMock()
            store = _create("s3", {"bucket": "test-bucket"})
        from was_server._storage_s3 import S3Storage

        assert isinstance(store, S3Storage)


class TestPostgresqlBackend:
    def test_missing_dsn_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_DSN"):
            _create("postgresql")

    def test_creates_instance(self) -> None:
        import was_server._storage_postgresql as pg_mod

        original = pg_mod.ConnectionPool
        pg_mod.ConnectionPool = lambda dsn: MagicMock()  # type: ignore[assignment]
        try:
            store = _create("postgresql", {"dsn": "postgresql://mock/test"})
            assert isinstance(store, pg_mod.PostgreSQLStorage)
        finally:
            pg_mod.ConnectionPool = original


class TestOneDriveBackend:
    def test_missing_client_id_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_CLIENT_ID"):
            _create("onedrive")

    def test_missing_client_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_CLIENT_SECRET"):
            _create("onedrive", {"client_id": "x"})

    def test_missing_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_TENANT_ID"):
            _create("onedrive", {"client_id": "x", "client_secret": "y"})  # nosec B105

    def test_creates_instance(self) -> None:
        with patch("was_server._storage_onedrive.msal"):
            store = _create("onedrive", {  # nosec B105
                "client_id": "x", "client_secret": "y", "tenant_id": "t",
            })
        from was_server._storage_onedrive import OneDriveStorage

        assert isinstance(store, OneDriveStorage)


class TestDropboxBackend:
    def test_creates_instance(self) -> None:
        with patch("was_server._storage_dropbox.dropbox") as mock_dbx_mod:
            mock_dbx_mod.Dropbox.return_value = MagicMock()
            store = _create("dropbox", {"access_token": "fake-token"})  # nosec B105
        from was_server._storage_dropbox import DropboxStorage

        assert isinstance(store, DropboxStorage)


class TestGDriveBackend:
    def test_missing_credentials_raises(self) -> None:
        with pytest.raises(ValueError, match="WAS_STORAGE_CREDENTIALS_JSON"):
            _create("gdrive")

    def test_creates_instance(self) -> None:
        with (
            patch("was_server._storage_gdrive.Credentials.from_service_account_info") as mock_creds,
            patch("was_server._storage_gdrive.build") as mock_build,
        ):
            mock_creds.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            # _find_or_create_folder is called in __init__, mock the files().list()
            mock_service = mock_build.return_value
            mock_files = mock_service.files.return_value
            mock_req = MagicMock()
            mock_req.execute.return_value = {"files": [{"id": "root-id"}]}
            mock_files.list.return_value = mock_req
            store = _create("gdrive", {"credentials_json": '{"type":"service_account"}'})
        from was_server._storage_gdrive import GoogleDriveStorage

        assert isinstance(store, GoogleDriveStorage)


class TestUnknownBackend:
    def test_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown storage backend"):
            _create("nosuchbackend")

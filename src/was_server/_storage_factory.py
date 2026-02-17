"""Factory for creating the configured storage backend."""

from __future__ import annotations

from was_server._settings import get_backend_name, get_storage_config
from was_server._storage import StorageBackend


def create_storage() -> StorageBackend:
    """Instantiate the storage backend selected by ``WAS_STORAGE_BACKEND``."""
    name = get_backend_name()
    config = get_storage_config()

    if name == "memory":
        from was_server._storage import MemoryStorage

        return MemoryStorage()

    if name == "filesystem":
        from was_server._storage_filesystem import FilesystemStorage

        return FilesystemStorage(root_dir=config.get("root_dir", "./was_data"))

    if name == "postgresql":
        from was_server._storage_postgresql import PostgreSQLStorage

        dsn = config.get("dsn")
        if not dsn:
            raise ValueError("WAS_STORAGE_DSN is required for the postgresql backend")
        return PostgreSQLStorage(dsn=dsn)

    if name == "s3":
        from was_server._storage_s3 import S3Storage

        bucket = config.get("bucket")
        if not bucket:
            raise ValueError("WAS_STORAGE_BUCKET is required for the s3 backend")
        return S3Storage(bucket=bucket, prefix=config.get("prefix", ""))

    if name == "onedrive":
        from was_server._storage_onedrive import OneDriveStorage

        for required in ("client_id", "client_secret", "tenant_id"):
            if required not in config:
                raise ValueError(f"WAS_STORAGE_{required.upper()} is required for the onedrive backend")
        return OneDriveStorage(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            tenant_id=config["tenant_id"],
            drive_id=config.get("drive_id"),
            root_folder=config.get("root_folder", "was_data"),
        )

    if name == "dropbox":
        from was_server._storage_dropbox import DropboxStorage

        return DropboxStorage(
            access_token=config.get("access_token"),
            refresh_token=config.get("refresh_token"),
            app_key=config.get("app_key"),
            app_secret=config.get("app_secret"),
            root_folder=config.get("root_folder", "was_data"),
        )

    if name == "gdrive":
        from was_server._storage_gdrive import GoogleDriveStorage

        credentials_json = config.get("credentials_json")
        if not credentials_json:
            raise ValueError("WAS_STORAGE_CREDENTIALS_JSON is required for the gdrive backend")
        return GoogleDriveStorage(
            credentials_json=credentials_json,
            root_folder=config.get("root_folder", "was_data"),
        )

    raise ValueError(f"Unknown storage backend: {name!r}")

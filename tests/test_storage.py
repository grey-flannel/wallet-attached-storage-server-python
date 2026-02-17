"""Storage backend conformance tests.

These tests run against every available backend to verify they implement
the ``StorageBackend`` protocol correctly.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

from was_server._storage import MemoryStorage, StorageBackend

ALL_BACKENDS = ["memory", "filesystem", "s3", "postgresql"]


@pytest.fixture(params=ALL_BACKENDS)
def store(request: pytest.FixtureRequest, tmp_path: str) -> Generator[StorageBackend]:
    """Parameterized storage backend fixture for conformance testing."""
    backend_name = request.param

    if backend_name == "memory":
        yield MemoryStorage()
        return

    if backend_name == "filesystem":
        from was_server._storage_filesystem import FilesystemStorage

        yield FilesystemStorage(root_dir=str(tmp_path))
        return

    if backend_name == "s3":
        try:
            import boto3
            from moto import mock_aws
        except ImportError:
            pytest.skip("moto not installed")
            return

        mock = mock_aws()
        mock.start()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        from was_server._storage_s3 import S3Storage

        yield S3Storage(bucket="test-bucket", prefix="test/")
        mock.stop()
        return

    if backend_name == "postgresql":
        dsn = os.environ.get("WAS_TEST_POSTGRESQL_DSN")
        if not dsn:
            pytest.skip("WAS_TEST_POSTGRESQL_DSN not set")
            return
        from was_server._storage_postgresql import PostgreSQLStorage

        s = PostgreSQLStorage(dsn=dsn)
        yield s
        s.close()
        return

    pytest.fail(f"Unknown backend: {backend_name}")


class TestSpaceCrud:
    def test_put_and_get(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        space = store.get_space("abc")
        assert space is not None
        assert space.id == "urn:uuid:abc"
        assert space.controller == "did:key:z1"

    def test_get_nonexistent(self, store: StorageBackend) -> None:
        assert store.get_space("missing") is None

    def test_put_updates_controller(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        space = store.get_space("abc")
        assert space is not None
        assert space.controller == "did:key:z2"

    def test_put_preserves_resources(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"data"

    def test_delete(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_space("abc") is True
        assert store.get_space("abc") is None

    def test_delete_nonexistent(self, store: StorageBackend) -> None:
        assert store.delete_space("missing") is False

    def test_list_by_controller(self, store: StorageBackend) -> None:
        store.put_space("a", "urn:uuid:a", "did:key:z1")
        store.put_space("b", "urn:uuid:b", "did:key:z1")
        store.put_space("c", "urn:uuid:c", "did:key:z2")
        spaces = store.list_spaces("did:key:z1")
        assert len(spaces) == 2
        ids = {s.id for s in spaces}
        assert ids == {"urn:uuid:a", "urn:uuid:b"}


class TestResourceCrud:
    def test_put_and_get(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"hello", "text/plain")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"hello"
        assert resource.content_type == "text/plain"

    def test_get_nonexistent_resource(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.get_resource("abc", "/missing") is None

    def test_get_resource_nonexistent_space(self, store: StorageBackend) -> None:
        assert store.get_resource("missing", "/file.txt") is None

    def test_put_resource_nonexistent_space_raises(self, store: StorageBackend) -> None:
        with pytest.raises(KeyError):
            store.put_resource("missing", "/file.txt", b"data", "text/plain")

    def test_delete_resource(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        assert store.delete_resource("abc", "/file.txt") is True
        assert store.get_resource("abc", "/file.txt") is None

    def test_delete_nonexistent_resource(self, store: StorageBackend) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_resource("abc", "/missing") is False

    def test_delete_resource_nonexistent_space(self, store: StorageBackend) -> None:
        assert store.delete_resource("missing", "/file.txt") is False

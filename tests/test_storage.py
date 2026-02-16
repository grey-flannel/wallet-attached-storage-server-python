"""Tests for the in-memory storage backend."""

from __future__ import annotations

import pytest

from was_server._storage import MemoryStorage


@pytest.fixture()
def store() -> MemoryStorage:
    return MemoryStorage()


class TestSpaceCrud:
    def test_put_and_get(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        space = store.get_space("abc")
        assert space is not None
        assert space.id == "urn:uuid:abc"
        assert space.controller == "did:key:z1"

    def test_get_nonexistent(self, store: MemoryStorage) -> None:
        assert store.get_space("missing") is None

    def test_put_updates_controller(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        space = store.get_space("abc")
        assert space is not None
        assert space.controller == "did:key:z2"

    def test_put_preserves_resources(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        store.put_space("abc", "urn:uuid:abc", "did:key:z2")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"data"

    def test_delete(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_space("abc") is True
        assert store.get_space("abc") is None

    def test_delete_nonexistent(self, store: MemoryStorage) -> None:
        assert store.delete_space("missing") is False

    def test_list_by_controller(self, store: MemoryStorage) -> None:
        store.put_space("a", "urn:uuid:a", "did:key:z1")
        store.put_space("b", "urn:uuid:b", "did:key:z1")
        store.put_space("c", "urn:uuid:c", "did:key:z2")
        spaces = store.list_spaces("did:key:z1")
        assert len(spaces) == 2
        ids = {s.id for s in spaces}
        assert ids == {"urn:uuid:a", "urn:uuid:b"}


class TestResourceCrud:
    def test_put_and_get(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"hello", "text/plain")
        resource = store.get_resource("abc", "/file.txt")
        assert resource is not None
        assert resource.content == b"hello"
        assert resource.content_type == "text/plain"

    def test_get_nonexistent_resource(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.get_resource("abc", "/missing") is None

    def test_get_resource_nonexistent_space(self, store: MemoryStorage) -> None:
        assert store.get_resource("missing", "/file.txt") is None

    def test_put_resource_nonexistent_space_raises(self, store: MemoryStorage) -> None:
        with pytest.raises(KeyError):
            store.put_resource("missing", "/file.txt", b"data", "text/plain")

    def test_delete_resource(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store.put_resource("abc", "/file.txt", b"data", "text/plain")
        assert store.delete_resource("abc", "/file.txt") is True
        assert store.get_resource("abc", "/file.txt") is None

    def test_delete_nonexistent_resource(self, store: MemoryStorage) -> None:
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")
        assert store.delete_resource("abc", "/missing") is False

    def test_delete_resource_nonexistent_space(self, store: MemoryStorage) -> None:
        assert store.delete_resource("missing", "/file.txt") is False

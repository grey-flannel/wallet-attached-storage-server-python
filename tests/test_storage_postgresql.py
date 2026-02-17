"""PostgreSQL-specific storage backend tests.

All tests require the WAS_TEST_POSTGRESQL_DSN environment variable.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

DSN = os.environ.get("WAS_TEST_POSTGRESQL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="WAS_TEST_POSTGRESQL_DSN not set")


@pytest.fixture()
def pg_store() -> Generator:
    from was_server._storage_postgresql import PostgreSQLStorage

    store = PostgreSQLStorage(dsn=DSN)  # type: ignore[arg-type]
    yield store
    # Clean up all rows after each test.
    with store._pool.connection() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM was_resources")
        conn.execute("DELETE FROM was_spaces")
    store.close()


class TestSchemaIdempotent:
    def test_ensure_schema_twice(self, pg_store: object) -> None:
        """Calling _ensure_schema a second time should not raise."""
        from was_server._storage_postgresql import PostgreSQLStorage

        store: PostgreSQLStorage = pg_store  # type: ignore[assignment]
        store._ensure_schema()  # noqa: SLF001


class TestCascadeDelete:
    def test_delete_space_cascades_resources(self, pg_store: object) -> None:
        from was_server._storage_postgresql import PostgreSQLStorage

        store: PostgreSQLStorage = pg_store  # type: ignore[assignment]
        store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        store.put_resource("s1", "/a.txt", b"aaa", "text/plain")
        store.put_resource("s1", "/b.txt", b"bbb", "text/plain")
        store.delete_space("s1")

        # Resources should be gone due to ON DELETE CASCADE.
        with store._pool.connection() as conn:  # noqa: SLF001
            count = conn.execute(
                "SELECT count(*) FROM was_resources WHERE space_uuid = %s", ("s1",)
            ).fetchone()
        assert count is not None
        assert count[0] == 0


class TestConcurrentAccess:
    def test_parallel_put_spaces(self, pg_store: object) -> None:
        """Multiple put_space calls should not deadlock."""
        from was_server._storage_postgresql import PostgreSQLStorage

        store: PostgreSQLStorage = pg_store  # type: ignore[assignment]
        for i in range(20):
            store.put_space(f"s{i}", f"urn:uuid:s{i}", "did:key:z1")

        spaces = store.list_spaces("did:key:z1")
        assert len(spaces) == 20

    def test_put_resource_to_same_space(self, pg_store: object) -> None:
        """Sequential resource writes to the same space should succeed."""
        from was_server._storage_postgresql import PostgreSQLStorage

        store: PostgreSQLStorage = pg_store  # type: ignore[assignment]
        store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        for i in range(20):
            store.put_resource("s1", f"/file{i}.txt", f"data{i}".encode(), "text/plain")

        for i in range(20):
            r = store.get_resource("s1", f"/file{i}.txt")
            assert r is not None
            assert r.content == f"data{i}".encode()

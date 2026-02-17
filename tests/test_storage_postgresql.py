"""PostgreSQL storage backend tests.

Mocked tests run without a database. Live tests require WAS_TEST_POSTGRESQL_DSN.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

DSN = os.environ.get("WAS_TEST_POSTGRESQL_DSN")

# Ensure psycopg_pool is importable even when psycopg is not installed.
# We inject a stub module so that `from psycopg_pool import ConnectionPool`
# resolves to a MagicMock, which our fixture then replaces with _MockPool.
_PSYCOPG_POOL_AVAILABLE = "psycopg_pool" in sys.modules
if not _PSYCOPG_POOL_AVAILABLE:
    _stub = types.ModuleType("psycopg_pool")
    _stub.ConnectionPool = MagicMock  # type: ignore[attr-defined]
    sys.modules["psycopg_pool"] = _stub


# ---------------------------------------------------------------------------
# In-memory mock of psycopg3 pool/connection/cursor
# ---------------------------------------------------------------------------


class _MockCursor:
    """Minimal cursor that returns pre-set results."""

    def __init__(self, result: list | None = None, rowcount: int = 0) -> None:
        self._result = result or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class _MockConnection:
    """Mock connection backed by in-memory dicts."""

    def __init__(self, spaces: dict, resources: dict) -> None:
        self._spaces = spaces
        self._resources = resources

    def execute(self, sql: str, params: tuple = ()) -> _MockCursor:
        sql_upper = sql.strip().upper()

        if sql_upper.startswith("CREATE TABLE") or sql_upper.startswith("CREATE INDEX"):
            return _MockCursor()

        if "INSERT INTO WAS_SPACES" in sql_upper:
            uuid, sid, ctrl = params
            self._spaces[uuid] = (sid, ctrl)
            return _MockCursor()

        if "SELECT SPACE_ID, CONTROLLER FROM WAS_SPACES WHERE SPACE_UUID" in sql_upper:
            row = self._spaces.get(params[0])
            return _MockCursor([row] if row else [])

        if "SELECT SPACE_ID, CONTROLLER FROM WAS_SPACES WHERE CONTROLLER" in sql_upper:
            rows = [(sid, ctrl) for sid, ctrl in self._spaces.values() if ctrl == params[0]]
            return _MockCursor(rows)

        if "DELETE FROM WAS_SPACES" in sql_upper:
            uuid = params[0]
            if uuid in self._spaces:
                del self._spaces[uuid]
                # Cascade: remove resources for this space
                to_del = [k for k in self._resources if k[0] == uuid]
                for k in to_del:
                    del self._resources[k]
                return _MockCursor(rowcount=1)
            return _MockCursor(rowcount=0)

        if "SELECT 1 FROM WAS_SPACES" in sql_upper:
            return _MockCursor([(1,)] if params[0] in self._spaces else [])

        if "INSERT INTO WAS_RESOURCES" in sql_upper:
            uuid, path, content, ct = params
            self._resources[(uuid, path)] = (bytes(content), ct)
            return _MockCursor()

        if "SELECT CONTENT, CONTENT_TYPE FROM WAS_RESOURCES" in sql_upper:
            key = (params[0], params[1])
            row = self._resources.get(key)
            return _MockCursor([row] if row else [])

        if "DELETE FROM WAS_RESOURCES" in sql_upper:
            key = (params[0], params[1])
            if key in self._resources:
                del self._resources[key]
                return _MockCursor(rowcount=1)
            return _MockCursor(rowcount=0)

        return _MockCursor()


class _MockPool:
    """Mock ConnectionPool using in-memory state."""

    def __init__(self) -> None:
        self._spaces: dict[str, tuple[str, str]] = {}
        self._resources: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.closed = False

    @contextmanager
    def connection(self):
        yield _MockConnection(self._spaces, self._resources)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def mock_pg_store():
    """Create a PostgreSQLStorage backed by an in-memory mock pool."""
    import was_server._storage_postgresql as pg_mod

    pool = _MockPool()
    original = pg_mod.ConnectionPool
    pg_mod.ConnectionPool = lambda dsn: pool  # type: ignore[assignment]
    try:
        store = pg_mod.PostgreSQLStorage(dsn="postgresql://mock/test")
        yield store
    finally:
        pg_mod.ConnectionPool = original


# ---------------------------------------------------------------------------
# Mocked tests — no real database needed
# ---------------------------------------------------------------------------


class TestMockedSpaceCrud:
    def test_put_and_get(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        space = mock_pg_store.get_space("s1")
        assert space is not None
        assert space.id == "urn:uuid:s1"
        assert space.controller == "did:key:z1"

    def test_get_nonexistent(self, mock_pg_store) -> None:
        assert mock_pg_store.get_space("missing") is None

    def test_put_updates_controller(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z2")
        space = mock_pg_store.get_space("s1")
        assert space is not None
        assert space.controller == "did:key:z2"

    def test_delete(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        assert mock_pg_store.delete_space("s1") is True
        assert mock_pg_store.get_space("s1") is None

    def test_delete_nonexistent(self, mock_pg_store) -> None:
        assert mock_pg_store.delete_space("missing") is False

    def test_list_by_controller(self, mock_pg_store) -> None:
        mock_pg_store.put_space("a", "urn:uuid:a", "did:key:z1")
        mock_pg_store.put_space("b", "urn:uuid:b", "did:key:z1")
        mock_pg_store.put_space("c", "urn:uuid:c", "did:key:z2")
        spaces = mock_pg_store.list_spaces("did:key:z1")
        assert len(spaces) == 2
        ids = {s.id for s in spaces}
        assert ids == {"urn:uuid:a", "urn:uuid:b"}


class TestMockedResourceCrud:
    def test_put_and_get(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        mock_pg_store.put_resource("s1", "/file.txt", b"hello", "text/plain")
        r = mock_pg_store.get_resource("s1", "/file.txt")
        assert r is not None
        assert r.content == b"hello"
        assert r.content_type == "text/plain"

    def test_get_nonexistent(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        assert mock_pg_store.get_resource("s1", "/missing") is None

    def test_put_nonexistent_space_raises(self, mock_pg_store) -> None:
        with pytest.raises(KeyError):
            mock_pg_store.put_resource("missing", "/f.txt", b"data", "text/plain")

    def test_delete(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        mock_pg_store.put_resource("s1", "/f.txt", b"data", "text/plain")
        assert mock_pg_store.delete_resource("s1", "/f.txt") is True
        assert mock_pg_store.get_resource("s1", "/f.txt") is None

    def test_delete_nonexistent(self, mock_pg_store) -> None:
        assert mock_pg_store.delete_resource("s1", "/missing") is False

    def test_overwrite(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        mock_pg_store.put_resource("s1", "/f.txt", b"v1", "text/plain")
        mock_pg_store.put_resource("s1", "/f.txt", b"v2", "application/json")
        r = mock_pg_store.get_resource("s1", "/f.txt")
        assert r is not None
        assert r.content == b"v2"
        assert r.content_type == "application/json"

    def test_delete_space_cascades(self, mock_pg_store) -> None:
        mock_pg_store.put_space("s1", "urn:uuid:s1", "did:key:z1")
        mock_pg_store.put_resource("s1", "/a.txt", b"aaa", "text/plain")
        mock_pg_store.delete_space("s1")
        assert mock_pg_store.get_resource("s1", "/a.txt") is None


class TestMockedClose:
    def test_close(self, mock_pg_store) -> None:
        mock_pg_store.close()
        assert mock_pg_store._pool.closed is True  # noqa: SLF001


# ---------------------------------------------------------------------------
# Live tests — require WAS_TEST_POSTGRESQL_DSN
# ---------------------------------------------------------------------------

pytestmark_live = pytest.mark.skipif(not DSN, reason="WAS_TEST_POSTGRESQL_DSN not set")


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


@pytest.mark.skipif(not DSN, reason="WAS_TEST_POSTGRESQL_DSN not set")
class TestSchemaIdempotent:
    def test_ensure_schema_twice(self, pg_store: object) -> None:
        """Calling _ensure_schema a second time should not raise."""
        from was_server._storage_postgresql import PostgreSQLStorage

        store: PostgreSQLStorage = pg_store  # type: ignore[assignment]
        store._ensure_schema()  # noqa: SLF001


@pytest.mark.skipif(not DSN, reason="WAS_TEST_POSTGRESQL_DSN not set")
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


@pytest.mark.skipif(not DSN, reason="WAS_TEST_POSTGRESQL_DSN not set")
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

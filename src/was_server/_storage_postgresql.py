"""PostgreSQL storage backend for WAS spaces and resources."""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from was_server._storage import StoredResource, StoredSpace


class PostgreSQLStorage:
    """Storage backend using PostgreSQL with psycopg3 and connection pooling."""

    def __init__(self, dsn: str) -> None:
        self._pool = ConnectionPool(dsn)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't already exist."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS was_spaces (
                    space_uuid TEXT PRIMARY KEY,
                    space_id   TEXT NOT NULL,
                    controller TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_spaces_controller ON was_spaces (controller)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS was_resources (
                    space_uuid   TEXT NOT NULL REFERENCES was_spaces(space_uuid) ON DELETE CASCADE,
                    path         TEXT NOT NULL,
                    content      BYTEA NOT NULL,
                    content_type TEXT NOT NULL,
                    PRIMARY KEY (space_uuid, path)
                )
                """
            )

    def close(self) -> None:
        """Close the connection pool."""
        self._pool.close()

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT space_id, controller FROM was_spaces WHERE space_uuid = %s",
                (space_uuid,),
            ).fetchone()
        if row is None:
            return None
        return StoredSpace(id=row[0], controller=row[1])

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO was_spaces (space_uuid, space_id, controller)
                VALUES (%s, %s, %s)
                ON CONFLICT (space_uuid) DO UPDATE SET controller = EXCLUDED.controller
                """,
                (space_uuid, space_id, controller),
            )

    def delete_space(self, space_uuid: str) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute("DELETE FROM was_spaces WHERE space_uuid = %s", (space_uuid,))
            return cur.rowcount > 0

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT space_id, controller FROM was_spaces WHERE controller = %s",
                (controller,),
            ).fetchall()
        return [StoredSpace(id=row[0], controller=row[1]) for row in rows]

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT content, content_type FROM was_resources WHERE space_uuid = %s AND path = %s",
                (space_uuid, path),
            ).fetchone()
        if row is None:
            return None
        return StoredResource(content=bytes(row[0]), content_type=row[1])

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        with self._pool.connection() as conn:
            space_exists = conn.execute(
                "SELECT 1 FROM was_spaces WHERE space_uuid = %s",
                (space_uuid,),
            ).fetchone()
            if space_exists is None:
                raise KeyError(f"Space {space_uuid!r} not found")
            conn.execute(
                """
                INSERT INTO was_resources (space_uuid, path, content, content_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (space_uuid, path)
                DO UPDATE SET content = EXCLUDED.content, content_type = EXCLUDED.content_type
                """,
                (space_uuid, path, content, content_type),
            )

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM was_resources WHERE space_uuid = %s AND path = %s",
                (space_uuid, path),
            )
            return cur.rowcount > 0

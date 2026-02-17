# PostgreSQL Backend

Persists spaces and resources to a PostgreSQL database using [psycopg3](https://www.psycopg.org/psycopg3/) with connection pooling.

## When to Use

- Production deployments that need durable, ACID-compliant storage
- Multi-server setups sharing a single database
- Environments where you already run PostgreSQL

## Installation

```bash
pip install "wallet-attached-storage-server[postgresql]"
```

This installs `psycopg[binary]` and `psycopg-pool`.

## Configuration

```bash
export WAS_STORAGE_BACKEND=postgresql
export WAS_STORAGE_DSN="postgresql://user:password@localhost:5432/wasdb"
```

## Environment Variables

| Variable              | Required | Default | Description                  |
|-----------------------|----------|---------|------------------------------|
| `WAS_STORAGE_BACKEND` | Yes      | --      | Set to `postgresql`          |
| `WAS_STORAGE_DSN`     | Yes      | --      | PostgreSQL connection string |

The DSN follows the standard [libpq connection string](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING) format.

## Database Setup

The server creates tables automatically on startup. No manual migration needed:

```sql
-- Created automatically by the server:
CREATE TABLE IF NOT EXISTS was_spaces (
    space_uuid TEXT PRIMARY KEY,
    space_id   TEXT NOT NULL,
    controller TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spaces_controller ON was_spaces (controller);

CREATE TABLE IF NOT EXISTS was_resources (
    space_uuid   TEXT NOT NULL REFERENCES was_spaces(space_uuid) ON DELETE CASCADE,
    path         TEXT NOT NULL,
    content      BYTEA NOT NULL,
    content_type TEXT NOT NULL,
    PRIMARY KEY (space_uuid, path)
);
```

## Running

```bash
# Create the database (if it doesn't exist)
createdb wasdb

export WAS_STORAGE_BACKEND=postgresql
export WAS_STORAGE_DSN="postgresql://localhost/wasdb"

uvicorn was_server:app --port 8080
```

## Implementation Notes

- **Schema management**: Tables are created with `IF NOT EXISTS` on every startup -- safe to restart without migration tooling
- **Cascade deletes**: Deleting a space automatically deletes all its resources via `ON DELETE CASCADE`
- **Connection pooling**: Uses `psycopg_pool.ConnectionPool` for efficient connection reuse
- **Upsert**: `put_space` uses `INSERT ... ON CONFLICT DO UPDATE` to update the controller without touching the space ID

## Testing with a Local Database

```bash
# Run conformance tests against a local PostgreSQL
export WAS_TEST_POSTGRESQL_DSN="postgresql://localhost/wasdb_test"
uv run -m pytest tests/test_storage.py -vv -k postgresql
uv run -m pytest tests/test_storage_postgresql.py -vv
```

## Limitations

- Stores resource content as `BYTEA` -- very large files (hundreds of MB) are better suited to S3 or filesystem storage
- No built-in partitioning or sharding -- scales vertically with PostgreSQL

# Wallet Attached Storage Server

Python server for the [Wallet Attached Storage](https://wallet.storage/spec) specification, built with FastAPI.

## Installation

```bash
pip install wallet-attached-storage-server
```

## Usage

```bash
# Start the server
uvicorn was_server:app --port 8080

# Or with auto-reload for development
uvicorn was_server:app --reload --port 8080
```

The server exposes the full WAS API at the root path. Clients authenticate with [Cavage draft-12 HTTP Signatures](https://datatracker.ietf.org/doc/html/draft-cavage-http-signatures-12) using Ed25519 `did:key` identifiers.

### API

#### Spaces

| Method   | Path          | Auth | Description                          |
|----------|---------------|------|--------------------------------------|
| `PUT`    | `/space/{id}` | Yes  | Create or update a space             |
| `GET`    | `/space/{id}` | Yes  | Read space metadata                  |
| `DELETE` | `/space/{id}` | Yes  | Delete space and all its resources   |
| `POST`   | `/spaces/`    | Yes  | Create a space (server-generated ID) |
| `GET`    | `/spaces/`    | Yes  | List spaces you control              |

#### Resources

| Method   | Path                    | Auth | Description              |
|----------|-------------------------|------|--------------------------|
| `GET`    | `/space/{id}/{path}`    | No   | Read a resource          |
| `PUT`    | `/space/{id}/{path}`    | Yes  | Create or update         |
| `POST`   | `/space/{id}/{path}`    | Yes  | Create (returns 201)     |
| `DELETE` | `/space/{id}/{path}`    | Yes  | Delete (idempotent)      |

### Authorization

Each space has a `controller` field set to a `did:key` DID. All write operations and space reads require an HTTP Signature whose signing key matches the space controller. Resource reads are unsigned (public).

### Storage Backend

The server ships with an in-memory storage backend. The storage layer is defined as a Python protocol, so you can swap in a file, database, or S3 backend by implementing `StorageBackend`.

## Development

```bash
uv run ruff check
uv run flake8 src tests
uv run bandit -r src
uv run bandit -r tests -s B101
uv run safety scan
uv run -m pytest -vv --cov=src --cov-report=term
```

CI runs all of the above on every push and PR (Python 3.11–3.14). To publish a release, tag and push:

```bash
git tag -sm "Initial release." "v0.1.0"
git push
```

### Acceptance Tests

The companion [client library](https://pypi.org/project/wallet-attached-storage-client/) includes a live test suite that runs against `localhost:8080`:

```bash
# Terminal 1
uv run uvicorn was_server:app --port 8080

# Terminal 2 (in the client repo)
uv run -m pytest tests/test_live.py -vv
```

## References

- [Wallet Attached Storage Specification](https://wallet.storage/spec)
- [Wallet Attached Storage Client (Python)](https://pypi.org/project/wallet-attached-storage-client/)
- [Wallet Attached Storage (JavaScript reference)](https://github.com/did-coop/wallet-attached-storage)
- [Wallet Attached Storage Specification (source)](https://github.com/did-coop/wallet-attached-storage-spec)

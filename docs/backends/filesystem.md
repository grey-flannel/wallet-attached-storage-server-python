# Filesystem Backend

Persists spaces and resources to the local filesystem. No external dependencies -- uses only the Python standard library.

## When to Use

- Single-server deployments where you want data to survive restarts
- Development with persistent state
- Environments where a database or cloud storage is overkill

## Installation

No extra dependencies needed:

```bash
pip install wallet-attached-storage-server
```

## Configuration

```bash
export WAS_STORAGE_BACKEND=filesystem
export WAS_STORAGE_ROOT_DIR=/var/lib/was_data   # optional, default: ./was_data
```

## Environment Variables

| Variable               | Required | Default      | Description                    |
|------------------------|----------|--------------|--------------------------------|
| `WAS_STORAGE_BACKEND`  | Yes      | --           | Set to `filesystem`            |
| `WAS_STORAGE_ROOT_DIR` | No       | `./was_data` | Root directory for stored data |

## Directory Layout

```text
{root_dir}/
  spaces/
    {space_uuid}/
      _meta.json                              # {"id": "urn:uuid:...", "controller": "did:key:..."}
      resources/
        %2Fgreeting.txt.data                  # raw resource bytes
        %2Fgreeting.txt.meta                  # {"content_type": "text/plain"}
```

Resource paths are percent-encoded to flat filenames, so `/greeting.txt` becomes `%2Fgreeting.txt`.

## Running

```bash
export WAS_STORAGE_BACKEND=filesystem
export WAS_STORAGE_ROOT_DIR=./was_data

uvicorn was_server:app --port 8080
```

## Implementation Notes

- **Atomic writes**: Files are written to a temp file first, then moved into place with `os.replace`, preventing partial writes on crash
- **Delete**: `delete_space` uses `shutil.rmtree` to remove the entire space directory
- **Permissions**: The server process needs read/write access to the root directory

## Limitations

- Not suitable for multi-server deployments (no shared state)
- No built-in backup or replication
- Performance degrades with very large numbers of spaces (linear scan on `list_spaces`)

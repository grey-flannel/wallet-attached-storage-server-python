# Memory Backend

The default storage backend. Stores all data in a Python dictionary -- fast and zero-config, but everything is lost when the process exits.

## When to Use

- Local development and testing
- CI pipelines
- Short-lived demo instances

## Configuration

No configuration needed. This is the default when `WAS_STORAGE_BACKEND` is unset.

```bash
# Explicit (optional -- this is the default)
export WAS_STORAGE_BACKEND=memory
```

## Environment Variables

| Variable              | Required | Default  | Description                          |
|-----------------------|----------|----------|--------------------------------------|
| `WAS_STORAGE_BACKEND` | No       | `memory` | Set to `memory` (or leave unset)     |

## Running

```bash
uvicorn was_server:app --port 8080
```

## Limitations

- Data is not persisted across restarts
- Not suitable for multi-process deployments (each worker gets its own dict)
- No storage size limits -- memory usage grows with data

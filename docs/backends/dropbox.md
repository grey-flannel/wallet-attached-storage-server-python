# Dropbox Backend

Persists spaces and resources to a Dropbox account using the [Dropbox Python SDK](https://github.com/dropbox/dropbox-sdk-python) (API v2).

## When to Use

- Personal or small-team deployments where Dropbox is already in use
- Scenarios where end users want their WAS data in their own Dropbox

## Installation

```bash
pip install "wallet-attached-storage-server[dropbox]"
```

This installs the `dropbox` SDK.

## Configuration

You can authenticate with either a long-lived access token or a refresh token (recommended for production):

### Option A: Access Token

```bash
export WAS_STORAGE_BACKEND=dropbox
export WAS_STORAGE_ACCESS_TOKEN=sl.xxxxx
```

### Option B: Refresh Token (recommended)

```bash
export WAS_STORAGE_BACKEND=dropbox
export WAS_STORAGE_REFRESH_TOKEN=xxxxx
export WAS_STORAGE_APP_KEY=xxxxx
export WAS_STORAGE_APP_SECRET=xxxxx           # optional but recommended
```

## Environment Variables

| Variable                    | Required | Default    | Description                 |
|-----------------------------|----------|------------|-----------------------------|
| `WAS_STORAGE_BACKEND`       | Yes      | --         | Set to `dropbox`            |
| `WAS_STORAGE_ACCESS_TOKEN`  | Option A | --         | Long-lived access token     |
| `WAS_STORAGE_REFRESH_TOKEN` | Option B | --         | OAuth2 refresh token        |
| `WAS_STORAGE_APP_KEY`       | Option B | --         | Dropbox app key             |
| `WAS_STORAGE_APP_SECRET`    | No       | --         | Dropbox app secret          |
| `WAS_STORAGE_ROOT_FOLDER`   | No       | `was_data` | Root folder name in Dropbox |

## Getting Credentials

1. Go to the [Dropbox App Console](https://www.dropbox.com/developers/apps) and create a new app
2. Choose "Scoped access" and "Full Dropbox" (or "App folder" for isolation)
3. Under Permissions, enable: `files.metadata.read`, `files.metadata.write`, `files.content.read`, `files.content.write`
4. Generate an access token (for quick testing) or set up the OAuth2 flow to get a refresh token (for production)

## Folder Layout

```text
/was_data/
  spaces/
    {space_uuid}/
      _meta.json                          # {"id": "urn:uuid:...", "controller": "did:key:..."}
      resources/
        %2Fgreeting.txt.data              # raw resource bytes
        %2Fgreeting.txt.meta              # {"content_type": "text/plain"}
```

## Running

```bash
export WAS_STORAGE_BACKEND=dropbox
export WAS_STORAGE_ACCESS_TOKEN=sl.xxxxx

uvicorn was_server:app --port 8080
```

## Implementation Notes

- **Authentication**: Supports both access tokens (quick setup) and refresh tokens (auto-renewal, no expiry concerns)
- **Folder deletion**: `delete_space` deletes the entire space folder recursively in one API call
- **Pagination**: `list_spaces` handles paginated folder listings via `files_list_folder_continue`
- **Overwrite mode**: All file uploads use `WriteMode.overwrite` for idempotent puts

## Limitations

- **Rate limits**: Dropbox API has rate limits that may affect high-throughput use cases
- **Latency**: Higher latency than local filesystem or S3 for individual operations
- `list_spaces` reads each space's `_meta.json` individually -- O(n) API calls
- Access tokens expire (use refresh tokens for long-running servers)

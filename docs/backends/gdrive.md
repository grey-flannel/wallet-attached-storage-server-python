# Google Drive Backend

Persists spaces and resources to Google Drive using a [service account](https://cloud.google.com/iam/docs/service-accounts) and the [Google Drive API v3](https://developers.google.com/drive/api/v3/about-sdk).

## When to Use

- Organizations using Google Workspace
- Scenarios where data should live in a Google Drive accessible to a service account

## Installation

```bash
pip install "wallet-attached-storage-server[gdrive]"
```

This installs `google-api-python-client` and `google-auth`.

## Configuration

```bash
export WAS_STORAGE_BACKEND=gdrive
export WAS_STORAGE_CREDENTIALS_JSON=/path/to/service-account.json
export WAS_STORAGE_ROOT_FOLDER=was_data                            # optional, default: was_data
```

The credentials can be either a file path or an inline JSON string:

```bash
# File path
export WAS_STORAGE_CREDENTIALS_JSON=/etc/was/service-account.json

# Inline JSON (useful in containers / CI)
export WAS_STORAGE_CREDENTIALS_JSON='{"type":"service_account","project_id":"my-project",...}'
```

## Environment Variables

| Variable                       | Required | Default    | Description                                         |
|--------------------------------|----------|------------|-----------------------------------------------------|
| `WAS_STORAGE_BACKEND`          | Yes      | --         | Set to `gdrive`                                     |
| `WAS_STORAGE_CREDENTIALS_JSON` | Yes      | --         | Service account JSON key (file path or inline JSON) |
| `WAS_STORAGE_ROOT_FOLDER`      | No       | `was_data` | Root folder name in Google Drive                    |

## Google Cloud Setup

1. Go to [Google Cloud Console > IAM & Admin > Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Create a service account (or use an existing one)
3. Create a JSON key for the service account and download it
4. Enable the [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) for your project

### Shared Drive / Folder Access

If you want the service account to write to a specific shared folder:

1. Note the service account's email address (e.g., `was-server@my-project.iam.gserviceaccount.com`)
2. Share the target Google Drive folder with that email address (Editor access)

The server will create its `was_data/spaces/` folder hierarchy inside the service account's Drive (or a shared folder if configured).

## Folder Layout

Google Drive is ID-based, not path-based, but the logical layout mirrors the filesystem:

```text
was_data/              (folder)
  spaces/              (folder)
    {space_uuid}/      (folder)
      _meta.json       (file: {"id": "urn:uuid:...", "controller": "did:key:..."})
      resources/       (folder)
        %2Ffile.data   (file: raw resource bytes)
        %2Ffile.meta   (file: {"content_type": "text/plain"})
```

## Running

```bash
export WAS_STORAGE_BACKEND=gdrive
export WAS_STORAGE_CREDENTIALS_JSON=/path/to/service-account.json

uvicorn was_server:app --port 8080
```

## Implementation Notes

- **Authentication**: Service account credentials -- no OAuth consent flow, no user interaction
- **Folder ID cache**: The backend maintains an in-memory cache of `(parent_id, folder_name) -> folder_id` mappings to avoid repeated Drive API lookups. The cache is invalidated when spaces are deleted
- **File creation**: Uses `MediaInMemoryUpload` with the correct MIME type. Existing files are updated in place (by file ID), not duplicated
- **Folder resolution**: `_find_or_create_folder()` searches for existing folders before creating, preventing duplicates
- **Credentials detection**: If the `WAS_STORAGE_CREDENTIALS_JSON` value contains `{`, it's treated as inline JSON; otherwise as a file path

## Limitations

- **Rate limits**: Google Drive API has [usage limits](https://developers.google.com/drive/api/guides/limits) (typically 20,000 queries per 100 seconds per project)
- **Latency**: Each operation involves one or more API calls to Google Drive
- **Folder cache**: The in-memory cache is per-process; if running multiple workers, each maintains its own cache
- `list_spaces` reads each space's `_meta.json` individually -- O(n) API calls
- Service account Drive storage is limited (15 GB by default, unless using a Workspace domain with more storage)

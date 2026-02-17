# OneDrive Backend

Persists spaces and resources to Microsoft OneDrive using [MSAL](https://github.com/AzureAD/microsoft-authentication-library-for-python) for authentication and the [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) for file operations.

## When to Use

- Organizations using Microsoft 365 / OneDrive for Business
- Scenarios where data should live in a specific user's or organization's OneDrive

## Installation

```bash
pip install "wallet-attached-storage-server[onedrive]"
```

This installs `msal` and `httpx`.

## Configuration

```bash
export WAS_STORAGE_BACKEND=onedrive
export WAS_STORAGE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export WAS_STORAGE_CLIENT_SECRET=xxxxx
export WAS_STORAGE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export WAS_STORAGE_DRIVE_ID=b!xxxxx                               # optional
export WAS_STORAGE_ROOT_FOLDER=was_data                           # optional, default: was_data
```

## Environment Variables

| Variable                    | Required | Default    | Description                      |
|-----------------------------|----------|------------|----------------------------------|
| `WAS_STORAGE_BACKEND`       | Yes      | --         | Set to `onedrive`                |
| `WAS_STORAGE_CLIENT_ID`     | Yes      | --         | Azure AD application (client) ID |
| `WAS_STORAGE_CLIENT_SECRET` | Yes      | --         | Azure AD client secret           |
| `WAS_STORAGE_TENANT_ID`     | Yes      | --         | Azure AD tenant ID               |
| `WAS_STORAGE_DRIVE_ID`      | No       | --         | Specific OneDrive drive ID       |
| `WAS_STORAGE_ROOT_FOLDER`   | No       | `was_data` | Root folder name in OneDrive     |

## Azure AD App Registration

1. Go to [Azure Portal > App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and create a new registration
2. Under **Certificates & secrets**, create a new client secret
3. Under **API permissions**, add these Microsoft Graph **application** permissions:
   - `Files.ReadWrite.All`
4. Click **Grant admin consent** for your organization

Note the **Application (client) ID**, **Directory (tenant) ID**, and the **client secret value**.

If you want to target a specific drive (e.g., a SharePoint document library), set `WAS_STORAGE_DRIVE_ID`. To find your drive ID:

```bash
# Using the Graph Explorer or CLI:
# GET https://graph.microsoft.com/v1.0/drives
```

## Folder Layout

```text
was_data/
  spaces/
    {space_uuid}/
      _meta.json                          # {"id": "urn:uuid:...", "controller": "did:key:..."}
      resources/
        %2Fgreeting.txt.data              # raw resource bytes
        %2Fgreeting.txt.meta              # {"content_type": "text/plain"}
```

## Running

```bash
export WAS_STORAGE_BACKEND=onedrive
export WAS_STORAGE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export WAS_STORAGE_CLIENT_SECRET=xxxxx
export WAS_STORAGE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

uvicorn was_server:app --port 8080
```

## Implementation Notes

- **Authentication**: Uses MSAL client credentials flow (server-to-server, no user interaction). MSAL handles token caching and renewal internally
- **Graph API**: All file operations use path-based addressing (`/drives/{id}/root:/{path}:/content`)
- **Content type**: Stored in a `.meta` sidecar JSON file alongside the `.data` file (simpler than Graph extended properties)
- **Folder deletion**: `delete_space` deletes the space folder recursively in one API call

## Limitations

- **Rate limits**: Microsoft Graph has [throttling limits](https://learn.microsoft.com/en-us/graph/throttling) that vary by service and tenant
- **Latency**: Higher latency than local backends; each operation is an HTTP call to the Graph API
- `list_spaces` reads each space's `_meta.json` individually -- O(n) API calls
- Requires Azure AD admin consent for application permissions

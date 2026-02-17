"""Environment-variable configuration for storage backend selection."""

from __future__ import annotations

import os


def get_backend_name() -> str:
    """Return the selected storage backend name (default: ``memory``)."""
    return os.environ.get("WAS_STORAGE_BACKEND", "memory").lower()


def get_storage_config() -> dict[str, str]:
    """Collect all ``WAS_STORAGE_*`` env vars (excluding ``WAS_STORAGE_BACKEND``) as backend config."""
    prefix = "WAS_STORAGE_"
    skip = f"{prefix}BACKEND"
    return {
        key.removeprefix(prefix).lower(): value
        for key, value in os.environ.items()
        if key.startswith(prefix) and key != skip
    }

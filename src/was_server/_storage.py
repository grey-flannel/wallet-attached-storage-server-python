"""Pluggable storage backend for WAS spaces and resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class StoredResource:
    """A stored resource within a space."""

    content: bytes
    content_type: str


@dataclass
class StoredSpace:
    """A stored WAS space."""

    id: str  # noqa: A003 — full urn:uuid: string
    controller: str  # DID
    resources: dict[str, StoredResource] = field(default_factory=dict)


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for WAS storage backends."""

    def get_space(self, space_uuid: str) -> StoredSpace | None: ...
    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None: ...
    def delete_space(self, space_uuid: str) -> bool: ...
    def list_spaces(self, controller: str) -> list[StoredSpace]: ...
    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None: ...
    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None: ...
    def delete_resource(self, space_uuid: str, path: str) -> bool: ...


class MemoryStorage:
    """In-memory storage backend backed by a dict."""

    def __init__(self) -> None:
        self._spaces: dict[str, StoredSpace] = {}

    def clear(self) -> None:
        """Remove all spaces and resources."""
        self._spaces.clear()

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        return self._spaces.get(space_uuid)

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        existing = self._spaces.get(space_uuid)
        if existing is not None:
            existing.controller = controller
        else:
            self._spaces[space_uuid] = StoredSpace(id=space_id, controller=controller)

    def delete_space(self, space_uuid: str) -> bool:
        return self._spaces.pop(space_uuid, None) is not None

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        return [s for s in self._spaces.values() if s.controller == controller]

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        space = self._spaces.get(space_uuid)
        if space is None:
            return None
        return space.resources.get(path)

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        space = self._spaces.get(space_uuid)
        if space is None:
            raise KeyError(f"Space {space_uuid!r} not found")
        space.resources[path] = StoredResource(content=content, content_type=content_type)

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        space = self._spaces.get(space_uuid)
        if space is None:
            return False
        return space.resources.pop(path, None) is not None

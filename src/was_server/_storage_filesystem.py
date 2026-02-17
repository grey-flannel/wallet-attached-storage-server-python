"""Filesystem storage backend for WAS spaces and resources."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
from pathlib import Path

from was_server._storage import StoredResource, StoredSpace


class FilesystemStorage:
    """Storage backend that persists spaces and resources to the local filesystem.

    Layout::

        {root_dir}/spaces/{space_uuid}/_meta.json
        {root_dir}/spaces/{space_uuid}/resources/{encoded_path}.data
        {root_dir}/spaces/{space_uuid}/resources/{encoded_path}.meta
    """

    def __init__(self, root_dir: str = "./was_data") -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _space_dir(self, space_uuid: str) -> Path:
        return self._root / "spaces" / space_uuid

    def _meta_path(self, space_uuid: str) -> Path:
        return self._space_dir(space_uuid) / "_meta.json"

    @staticmethod
    def _encode_path(path: str) -> str:
        return urllib.parse.quote(path, safe="")

    def _resource_data_path(self, space_uuid: str, path: str) -> Path:
        return self._space_dir(space_uuid) / "resources" / f"{self._encode_path(path)}.data"

    def _resource_meta_path(self, space_uuid: str, path: str) -> Path:
        return self._space_dir(space_uuid) / "resources" / f"{self._encode_path(path)}.meta"

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        """Write data atomically via temp file + rename."""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent)
        try:
            os.write(fd, data)
            os.close(fd)
            os.replace(tmp, target)
        except BaseException:
            os.close(fd) if not os.get_inheritable(fd) else None  # noqa: E501
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        meta_path = self._meta_path(space_uuid)
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        return StoredSpace(id=meta["id"], controller=meta["controller"])

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        meta = {"id": space_id, "controller": controller}
        meta_bytes = json.dumps(meta).encode()
        self._atomic_write(self._meta_path(space_uuid), meta_bytes)

    def delete_space(self, space_uuid: str) -> bool:
        space_dir = self._space_dir(space_uuid)
        if not space_dir.exists():
            return False
        shutil.rmtree(space_dir)
        return True

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        spaces_dir = self._root / "spaces"
        if not spaces_dir.exists():
            return []
        result: list[StoredSpace] = []
        for entry in spaces_dir.iterdir():
            if not entry.is_dir():
                continue
            meta_path = entry / "_meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            if meta.get("controller") == controller:
                result.append(StoredSpace(id=meta["id"], controller=meta["controller"]))
        return result

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        data_path = self._resource_data_path(space_uuid, path)
        meta_path = self._resource_meta_path(space_uuid, path)
        if not data_path.exists() or not meta_path.exists():
            return None
        content = data_path.read_bytes()
        meta = json.loads(meta_path.read_text())
        return StoredResource(content=content, content_type=meta["content_type"])

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        if not self._meta_path(space_uuid).exists():
            raise KeyError(f"Space {space_uuid!r} not found")
        self._atomic_write(self._resource_data_path(space_uuid, path), content)
        meta_bytes = json.dumps({"content_type": content_type}).encode()
        self._atomic_write(self._resource_meta_path(space_uuid, path), meta_bytes)

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        data_path = self._resource_data_path(space_uuid, path)
        meta_path = self._resource_meta_path(space_uuid, path)
        if not data_path.exists():
            return False
        data_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        return True

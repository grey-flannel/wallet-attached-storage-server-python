"""Amazon S3 storage backend for WAS spaces and resources."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from was_server._storage import (
    StoredResource,
    StoredSpace,
    encode_resource_path,
    parse_space_meta,
    serialize_space_meta,
)


class S3Storage:
    """Storage backend that persists spaces and resources to Amazon S3.

    Key layout::

        {prefix}spaces/{space_uuid}/_meta.json
        {prefix}spaces/{space_uuid}/resources/{encoded_path}
    """

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._client = boto3.client("s3")

    def _meta_key(self, space_uuid: str) -> str:
        return f"{self._prefix}spaces/{space_uuid}/_meta.json"

    def _resource_key(self, space_uuid: str, path: str) -> str:
        return f"{self._prefix}spaces/{space_uuid}/resources/{encode_resource_path(path)}"

    def _space_prefix(self, space_uuid: str) -> str:
        return f"{self._prefix}spaces/{space_uuid}/"

    def get_space(self, space_uuid: str) -> StoredSpace | None:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._meta_key(space_uuid))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
        return parse_space_meta(resp["Body"].read())

    def put_space(self, space_uuid: str, space_id: str, controller: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._meta_key(space_uuid),
            Body=serialize_space_meta(space_id, controller),
            ContentType="application/json",
        )

    def delete_space(self, space_uuid: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._meta_key(space_uuid))
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

        prefix = self._space_prefix(space_uuid)
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
        return True

    def list_spaces(self, controller: str) -> list[StoredSpace]:
        prefix = f"{self._prefix}spaces/"
        result: list[StoredSpace] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                space_uuid = cp["Prefix"][len(prefix):].rstrip("/")
                try:
                    resp = self._client.get_object(Bucket=self._bucket, Key=self._meta_key(space_uuid))
                except ClientError as e:
                    if e.response["Error"]["Code"] == "NoSuchKey":
                        continue
                    raise
                space = parse_space_meta(resp["Body"].read())
                if space.controller == controller:
                    result.append(space)
        return result

    def get_resource(self, space_uuid: str, path: str) -> StoredResource | None:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._resource_key(space_uuid, path))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
        return StoredResource(
            content=resp["Body"].read(),
            content_type=resp["ContentType"],
        )

    def put_resource(self, space_uuid: str, path: str, content: bytes, content_type: str) -> None:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._meta_key(space_uuid))
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise KeyError(f"Space {space_uuid!r} not found") from None
            raise
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._resource_key(space_uuid, path),
            Body=content,
            ContentType=content_type,
        )

    def delete_resource(self, space_uuid: str, path: str) -> bool:
        key = self._resource_key(space_uuid, path)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

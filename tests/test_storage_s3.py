"""S3-specific storage backend tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from was_server._storage_s3 import S3Storage


@pytest.fixture
def s3_env() -> Generator[Any]:
    """Provide a moto-mocked S3 environment with a pre-created bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client


class TestPrefixIsolation:
    def test_different_prefixes_do_not_interfere(self, s3_env: Any) -> None:
        store_a = S3Storage(bucket="test-bucket", prefix="alpha/")
        store_b = S3Storage(bucket="test-bucket", prefix="beta/")

        store_a.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store_b.put_space("abc", "urn:uuid:abc", "did:key:z2")

        space_a = store_a.get_space("abc")
        space_b = store_b.get_space("abc")
        assert space_a is not None
        assert space_b is not None
        assert space_a.controller == "did:key:z1"
        assert space_b.controller == "did:key:z2"

    def test_list_spaces_isolated_by_prefix(self, s3_env: Any) -> None:
        store_a = S3Storage(bucket="test-bucket", prefix="alpha/")
        store_b = S3Storage(bucket="test-bucket", prefix="beta/")

        store_a.put_space("a1", "urn:uuid:a1", "did:key:z1")
        store_b.put_space("b1", "urn:uuid:b1", "did:key:z1")

        spaces = store_a.list_spaces("did:key:z1")
        assert len(spaces) == 1
        assert spaces[0].id == "urn:uuid:a1"

    def test_delete_space_isolated_by_prefix(self, s3_env: Any) -> None:
        store_a = S3Storage(bucket="test-bucket", prefix="alpha/")
        store_b = S3Storage(bucket="test-bucket", prefix="beta/")

        store_a.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store_b.put_space("abc", "urn:uuid:abc", "did:key:z1")

        store_a.delete_space("abc")
        assert store_a.get_space("abc") is None
        assert store_b.get_space("abc") is not None

    def test_resources_isolated_by_prefix(self, s3_env: Any) -> None:
        store_a = S3Storage(bucket="test-bucket", prefix="alpha/")
        store_b = S3Storage(bucket="test-bucket", prefix="beta/")

        store_a.put_space("abc", "urn:uuid:abc", "did:key:z1")
        store_b.put_space("abc", "urn:uuid:abc", "did:key:z1")

        store_a.put_resource("abc", "/file.txt", b"alpha-data", "text/plain")
        store_b.put_resource("abc", "/file.txt", b"beta-data", "text/plain")

        res_a = store_a.get_resource("abc", "/file.txt")
        res_b = store_b.get_resource("abc", "/file.txt")
        assert res_a is not None and res_a.content == b"alpha-data"
        assert res_b is not None and res_b.content == b"beta-data"


class TestLargeResource:
    def test_large_content_round_trip(self, s3_env: Any) -> None:
        store = S3Storage(bucket="test-bucket", prefix="test/")
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")

        large_content = b"x" * (5 * 1024 * 1024)  # 5 MB
        store.put_resource("abc", "/big.bin", large_content, "application/octet-stream")

        resource = store.get_resource("abc", "/big.bin")
        assert resource is not None
        assert len(resource.content) == 5 * 1024 * 1024
        assert resource.content == large_content


class TestContentTypePreservation:
    def test_content_type_preserved_via_s3_native(self, s3_env: Any) -> None:
        store = S3Storage(bucket="test-bucket", prefix="test/")
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")

        store.put_resource("abc", "/doc.html", b"<html></html>", "text/html; charset=utf-8")
        resource = store.get_resource("abc", "/doc.html")
        assert resource is not None
        assert resource.content_type == "text/html; charset=utf-8"

    def test_various_content_types(self, s3_env: Any) -> None:
        store = S3Storage(bucket="test-bucket", prefix="test/")
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")

        types = [
            ("image/png", b"\x89PNG"),
            ("application/json", b'{"key": "value"}'),
            ("text/plain", b"hello world"),
            ("application/octet-stream", b"\x00\x01\x02"),
        ]
        for ct, body in types:
            path = f"/{ct.replace('/', '_')}"
            store.put_resource("abc", path, body, ct)
            resource = store.get_resource("abc", path)
            assert resource is not None
            assert resource.content_type == ct


class TestPaginatedDelete:
    def test_delete_space_with_many_resources(self, s3_env: Any) -> None:
        store = S3Storage(bucket="test-bucket", prefix="test/")
        store.put_space("abc", "urn:uuid:abc", "did:key:z1")

        # Create more resources than a single list_objects_v2 page (default 1000)
        for i in range(1050):
            store.put_resource("abc", f"/file-{i:04d}.txt", b"data", "text/plain")

        assert store.delete_space("abc") is True
        assert store.get_space("abc") is None

        # Verify no objects remain under the space prefix
        resp = s3_env.list_objects_v2(Bucket="test-bucket", Prefix="test/spaces/abc/")
        assert resp.get("KeyCount", 0) == 0

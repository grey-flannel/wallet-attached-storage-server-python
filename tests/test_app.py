"""Tests for the FastAPI application routes."""

from __future__ import annotations

import json

from .conftest import Ed25519TestSigner, make_auth_header, provision_space


class TestSpaceLifecycle:
    def test_provision_space(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        path = f"/space/{space_uuid}"
        body = json.dumps({"id": f"urn:uuid:{space_uuid}", "controller": signer.controller})
        auth = make_auth_header(signer, "PUT", path)
        resp = test_client.put(path, content=body, headers={"authorization": auth, "content-type": "application/json"})
        assert resp.status_code == 204

    def test_get_space(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        path = f"/space/{space_uuid}"

        auth = make_auth_header(signer, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.is_success
        data = resp.json()
        assert data["controller"] == signer.controller

    def test_get_nonexistent_space(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/space/00000000-0000-0000-0000-000000000000"
        auth = make_auth_header(signer, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.status_code == 404

    def test_delete_space(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        path = f"/space/{space_uuid}"

        auth = make_auth_header(signer, "DELETE", path)
        resp = test_client.delete(path, headers={"authorization": auth})
        assert resp.status_code == 204

        # Confirm it's gone
        auth = make_auth_header(signer, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.status_code == 404

    def test_delete_nonexistent_space(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/space/00000000-0000-0000-0000-000000000000"
        auth = make_auth_header(signer, "DELETE", path)
        resp = test_client.delete(path, headers={"authorization": auth})
        assert resp.status_code == 204


class TestResourceCrud:
    def test_put_and_get_text(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/greeting.txt"

        auth = make_auth_header(signer, "PUT", resource_path)
        resp = test_client.put(
            resource_path, content=b"Hello, WAS!", headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.is_success

        resp = test_client.get(resource_path)
        assert resp.is_success
        assert resp.text == "Hello, WAS!"

    def test_put_and_get_json(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/data.json"
        doc = {"key": "value", "number": 42}

        auth = make_auth_header(signer, "PUT", resource_path)
        test_client.put(
            resource_path,
            content=json.dumps(doc).encode(),
            headers={"authorization": auth, "content-type": "application/json"},
        )

        resp = test_client.get(resource_path)
        assert resp.is_success
        assert resp.json() == doc

    def test_put_and_get_binary(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/blob.bin"
        payload = bytes(range(256))

        auth = make_auth_header(signer, "PUT", resource_path)
        test_client.put(
            resource_path,
            content=payload,
            headers={"authorization": auth, "content-type": "application/octet-stream"},
        )

        resp = test_client.get(resource_path)
        assert resp.is_success
        assert resp.content == payload

    def test_put_same_path_twice(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/twice.txt"

        auth = make_auth_header(signer, "PUT", resource_path)
        resp1 = test_client.put(
            resource_path, content=b"first", headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp1.is_success

        auth = make_auth_header(signer, "PUT", resource_path)
        resp2 = test_client.put(
            resource_path, content=b"second", headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp2.is_success

    def test_delete_resource(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/to-delete.txt"

        auth = make_auth_header(signer, "PUT", resource_path)
        test_client.put(
            resource_path, content=b"ephemeral", headers={"authorization": auth, "content-type": "text/plain"},
        )

        auth = make_auth_header(signer, "DELETE", resource_path)
        resp = test_client.delete(resource_path, headers={"authorization": auth})
        assert resp.is_success

        resp = test_client.get(resource_path)
        assert resp.status_code == 404

    def test_get_nonexistent_resource(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resp = test_client.get(f"/space/{space_uuid}/does-not-exist")
        assert resp.status_code == 404

    def test_unsigned_get_allowed(self, signer: Ed25519TestSigner, test_client) -> None:
        """Resources should be readable without auth (unsigned reads)."""
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/public.txt"

        auth = make_auth_header(signer, "PUT", resource_path)
        test_client.put(
            resource_path, content=b"public content", headers={"authorization": auth, "content-type": "text/plain"},
        )

        # GET without auth
        resp = test_client.get(resource_path)
        assert resp.status_code == 200
        assert resp.text == "public content"


class TestAuth:
    def test_missing_auth_rejected(self, test_client) -> None:
        resp = test_client.get("/space/some-uuid")
        assert resp.status_code == 401

    def test_different_signer_cannot_write(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        other = Ed25519TestSigner()
        resource_path = f"/space/{space_uuid}/intruder.txt"
        auth = make_auth_header(other, "PUT", resource_path)
        resp = test_client.put(
            resource_path, content=b"unauthorized", headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.status_code == 403

    def test_different_signer_cannot_read_space(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        other = Ed25519TestSigner()
        path = f"/space/{space_uuid}"
        auth = make_auth_header(other, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.status_code == 403

    def test_different_signer_cannot_delete_space(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        other = Ed25519TestSigner()
        path = f"/space/{space_uuid}"
        auth = make_auth_header(other, "DELETE", path)
        resp = test_client.delete(path, headers={"authorization": auth})
        assert resp.status_code == 403


class TestCreateSpace:
    """POST /spaces/ — server-generated space ID."""

    def test_create_returns_201(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/spaces/"
        auth = make_auth_header(signer, "POST", path)
        resp = test_client.post(path, headers={"authorization": auth})
        assert resp.status_code == 201
        assert "location" in resp.headers
        assert resp.headers["location"].startswith("/space/")

    def test_created_space_is_retrievable(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/spaces/"
        auth = make_auth_header(signer, "POST", path)
        resp = test_client.post(path, headers={"authorization": auth})
        location = resp.headers["location"]

        auth = make_auth_header(signer, "GET", location)
        resp = test_client.get(location, headers={"authorization": auth})
        assert resp.is_success
        data = resp.json()
        assert data["controller"] == signer.controller
        assert data["id"].startswith("urn:uuid:")

    def test_create_without_auth_rejected(self, test_client) -> None:
        resp = test_client.post("/spaces/")
        assert resp.status_code == 401


class TestListSpaces:
    """GET /spaces/ — list spaces by authenticated controller."""

    def test_empty_list(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/spaces/"
        auth = make_auth_header(signer, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.is_success
        assert resp.json() == []

    def test_lists_own_spaces(self, signer: Ed25519TestSigner, test_client) -> None:
        provision_space(signer, test_client, "aaaa0000-0000-0000-0000-000000000001")
        provision_space(signer, test_client, "aaaa0000-0000-0000-0000-000000000002")

        path = "/spaces/"
        auth = make_auth_header(signer, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.is_success
        items = resp.json()
        assert len(items) == 2

    def test_does_not_list_other_controllers_spaces(self, signer: Ed25519TestSigner, test_client) -> None:
        provision_space(signer, test_client)
        other = Ed25519TestSigner()
        path = "/spaces/"
        auth = make_auth_header(other, "GET", path)
        resp = test_client.get(path, headers={"authorization": auth})
        assert resp.is_success
        assert resp.json() == []

    def test_list_without_auth_rejected(self, test_client) -> None:
        resp = test_client.get("/spaces/")
        assert resp.status_code == 401


class TestPostResource:
    """POST /space/{id}/{path} — create resource (returns 201)."""

    def test_post_creates_resource(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        resource_path = f"/space/{space_uuid}/created.txt"

        auth = make_auth_header(signer, "POST", resource_path)
        resp = test_client.post(
            resource_path, content=b"new content",
            headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.status_code == 201

        resp = test_client.get(resource_path)
        assert resp.text == "new content"

    def test_post_to_nonexistent_space(self, signer: Ed25519TestSigner, test_client) -> None:
        resource_path = "/space/00000000-0000-0000-0000-000000000000/file.txt"
        auth = make_auth_header(signer, "POST", resource_path)
        resp = test_client.post(
            resource_path, content=b"data",
            headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.status_code == 404

    def test_post_wrong_controller_rejected(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        other = Ed25519TestSigner()
        resource_path = f"/space/{space_uuid}/intruder.txt"
        auth = make_auth_header(other, "POST", resource_path)
        resp = test_client.post(
            resource_path, content=b"bad",
            headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.status_code == 403

    def test_post_without_auth_rejected(self, test_client) -> None:
        resp = test_client.post("/space/some-uuid/file.txt", content=b"data")
        assert resp.status_code == 401


class TestPutSpaceValidation:
    """Additional PUT /space/{id} edge cases."""

    def test_missing_body_fields(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/space/test-uuid"
        auth = make_auth_header(signer, "PUT", path)
        resp = test_client.put(
            path, content=json.dumps({"id": "urn:uuid:test-uuid"}).encode(),
            headers={"authorization": auth, "content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_controller_mismatch(self, signer: Ed25519TestSigner, test_client) -> None:
        path = "/space/test-uuid"
        auth = make_auth_header(signer, "PUT", path)
        resp = test_client.put(
            path, content=json.dumps({"id": "urn:uuid:test-uuid", "controller": "did:key:zOTHER"}).encode(),
            headers={"authorization": auth, "content-type": "application/json"},
        )
        assert resp.status_code == 403


class TestPutResourceValidation:
    """Additional PUT /space/{id}/{path} edge cases."""

    def test_put_resource_nonexistent_space(self, signer: Ed25519TestSigner, test_client) -> None:
        resource_path = "/space/00000000-0000-0000-0000-000000000000/file.txt"
        auth = make_auth_header(signer, "PUT", resource_path)
        resp = test_client.put(
            resource_path, content=b"data",
            headers={"authorization": auth, "content-type": "text/plain"},
        )
        assert resp.status_code == 404


class TestDeleteResourceValidation:
    """Additional DELETE /space/{id}/{path} edge cases."""

    def test_delete_resource_wrong_controller(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)
        other = Ed25519TestSigner()
        resource_path = f"/space/{space_uuid}/file.txt"
        auth = make_auth_header(other, "DELETE", resource_path)
        resp = test_client.delete(resource_path, headers={"authorization": auth})
        assert resp.status_code == 403


class TestMultipleResources:
    def test_independent_resources(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)

        for name, content in [("file-a.txt", b"aaa"), ("file-b.txt", b"bbb")]:
            rpath = f"/space/{space_uuid}/{name}"
            auth = make_auth_header(signer, "PUT", rpath)
            test_client.put(rpath, content=content, headers={"authorization": auth, "content-type": "text/plain"})

        assert test_client.get(f"/space/{space_uuid}/file-a.txt").text == "aaa"
        assert test_client.get(f"/space/{space_uuid}/file-b.txt").text == "bbb"

    def test_delete_one_preserves_other(self, signer: Ed25519TestSigner, test_client) -> None:
        space_uuid = provision_space(signer, test_client)

        for name, content in [("keep.txt", b"keep me"), ("remove.txt", b"delete me")]:
            rpath = f"/space/{space_uuid}/{name}"
            auth = make_auth_header(signer, "PUT", rpath)
            test_client.put(rpath, content=content, headers={"authorization": auth, "content-type": "text/plain"})

        auth = make_auth_header(signer, "DELETE", f"/space/{space_uuid}/remove.txt")
        test_client.delete(f"/space/{space_uuid}/remove.txt", headers={"authorization": auth})

        assert test_client.get(f"/space/{space_uuid}/remove.txt").status_code == 404
        assert test_client.get(f"/space/{space_uuid}/keep.txt").text == "keep me"

from __future__ import annotations

import base64
import json
import math
import time

import base58
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from was_server._app import app, storage
from was_server._http_signature import _DEFAULT_INCLUDE_HEADERS, build_signature_string

# Multicodec prefix for Ed25519 public keys (0xed 0x01)
_MULTICODEC_ED25519_PUB = b"\xed\x01"

_EXPIRATION_SECONDS = 30


class Ed25519TestSigner:
    """Ed25519 test signer using ``cryptography`` library with proper did:key format.

    Produces the same ``did:key:z6Mk...#z6Mk...`` identifiers as the real ``Ed25519Signer``
    in the client library, which is required for server-side ``extract_public_key`` to work.
    """

    def __init__(self) -> None:
        self._private_key = Ed25519PrivateKey.generate()
        pub_bytes = self._private_key.public_key().public_bytes_raw()
        multikey = _MULTICODEC_ED25519_PUB + pub_bytes
        fingerprint = f"z{base58.b58encode(multikey).decode()}"
        self._controller = f"did:key:{fingerprint}"
        self._id = f"{self._controller}#{fingerprint}"

    @property
    def id(self) -> str:
        return self._id

    @property
    def controller(self) -> str:
        return self._controller

    def sign(self, data: bytes) -> bytes:
        return self._private_key.sign(data)


def make_auth_header(signer: Ed25519TestSigner, method: str, path: str) -> str:
    """Build a valid Authorization: Signature header for testing."""
    now = time.time()
    created = math.floor(now)
    expires = math.floor(now + _EXPIRATION_SECONDS)

    sig_string = build_signature_string(method=method, path=path, created=created, expires=expires, key_id=signer.id)
    sig_bytes = signer.sign(sig_string.encode("utf-8"))
    sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode("ascii").rstrip("=")

    headers_param = " ".join(_DEFAULT_INCLUDE_HEADERS)
    return (
        f'Signature keyId="{signer.id}",'
        f'headers="{headers_param}",'
        f'signature="{sig_b64}",'
        f'created="{created}",'
        f'expires="{expires}"'
    )


def provision_space(signer: Ed25519TestSigner, test_client: TestClient,
                    space_uuid: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479") -> str:
    """Create a space for testing. Returns the space UUID."""
    path = f"/space/{space_uuid}"
    body = json.dumps({"id": f"urn:uuid:{space_uuid}", "controller": signer.controller})
    auth = make_auth_header(signer, "PUT", path)
    test_client.put(path, content=body, headers={"authorization": auth, "content-type": "application/json"})
    return space_uuid


@pytest.fixture()
def signer() -> Ed25519TestSigner:
    return Ed25519TestSigner()


@pytest.fixture()
def test_client() -> TestClient:
    storage.clear()
    return TestClient(app)

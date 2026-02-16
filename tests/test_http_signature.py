"""Tests for HTTP Signature parsing, key extraction, and verification."""

from __future__ import annotations

import base64
import math
import time

import base58
import pytest

from was_server._http_signature import (
    build_signature_string,
    extract_public_key,
    parse_authorization_header,
    verify_signature,
)

from .conftest import Ed25519TestSigner, make_auth_header


class TestBuildSignatureString:
    def test_default_headers(self) -> None:
        result = build_signature_string(
            method="GET",
            path="/space/abc-123/my-resource",
            created=1700000000,
            expires=1700000030,
            key_id="did:key:test",
        )
        lines = result.split("\n")
        assert len(lines) == 4
        assert lines[0] == "(created): 1700000000"
        assert lines[1] == "(expires): 1700000030"
        assert lines[2] == "(key-id): did:key:test"
        assert lines[3] == "(request-target): get /space/abc-123/my-resource"

    def test_method_lowercased(self) -> None:
        result = build_signature_string(method="PUT", path="/space/abc", created=0, expires=0, key_id="k")
        assert "(request-target): put /space/abc" in result

    def test_unsupported_header_raises(self) -> None:
        with pytest.raises(ValueError):
            build_signature_string(method="GET", path="/", created=0, expires=0, key_id="k", include_headers=["host"])


class TestParseAuthorizationHeader:
    def test_valid_header(self) -> None:
        header = (
            'Signature keyId="did:key:z6Mk#z6Mk",'
            'headers="(created) (expires) (key-id) (request-target)",'
            'signature="dGVzdA",'
            'created="1700000000",'
            'expires="1700000030"'
        )
        parsed = parse_authorization_header(header)
        assert parsed.key_id == "did:key:z6Mk#z6Mk"
        assert parsed.controller == "did:key:z6Mk"
        assert parsed.headers == ["(created)", "(expires)", "(key-id)", "(request-target)"]
        assert parsed.created == 1700000000
        assert parsed.expires == 1700000030

    def test_missing_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            parse_authorization_header('Bearer token123')

    def test_missing_params_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing signature parameters"):
            parse_authorization_header('Signature keyId="x"')


class TestExtractPublicKey:
    def test_extract_from_did_key(self) -> None:
        signer = Ed25519TestSigner()
        # The signer's controller is did:key:z6Mk...
        key = extract_public_key(signer.controller)
        assert key is not None

    def test_extract_from_did_key_with_fragment(self) -> None:
        signer = Ed25519TestSigner()
        # The signer's id has a fragment: did:key:z6Mk...#z6Mk...
        key = extract_public_key(signer.id)
        assert key is not None

    def test_invalid_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected did:key:z"):
            extract_public_key("did:key:abc123")

    def test_invalid_multicodec_raises(self) -> None:
        bad = b"\x00\x00" + b"\x00" * 32
        encoded = f"did:key:z{base58.b58encode(bad).decode()}"
        with pytest.raises(ValueError, match="multicodec prefix"):
            extract_public_key(encoded)


class TestVerifySignature:
    def test_roundtrip(self) -> None:
        """Sign with Ed25519TestSigner, verify with verify_signature."""
        signer = Ed25519TestSigner()
        method = "PUT"
        path = "/space/test-uuid/data"
        auth = make_auth_header(signer, method, path)
        parsed = verify_signature(auth, method, path)
        assert parsed.controller == signer.controller

    def test_expired_signature_rejected(self) -> None:
        signer = Ed25519TestSigner()
        created = 1700000000
        expires = 1700000001  # already expired
        key_id = signer.id

        sig_string = build_signature_string(
            method="GET", path="/test", created=created, expires=expires, key_id=key_id,
        )
        sig_bytes = signer.sign(sig_string.encode("utf-8"))
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode("ascii").rstrip("=")

        header = (
            f'Signature keyId="{key_id}",'
            f'headers="(created) (expires) (key-id) (request-target)",'
            f'signature="{sig_b64}",'
            f'created="{created}",'
            f'expires="{expires}"'
        )
        with pytest.raises(ValueError, match="expired"):
            verify_signature(header, "GET", "/test")

    def test_tampered_signature_rejected(self) -> None:
        signer = Ed25519TestSigner()
        now = time.time()
        created = math.floor(now)
        expires = math.floor(now + 30)
        key_id = signer.id

        sig_string = build_signature_string(
            method="GET", path="/test", created=created, expires=expires, key_id=key_id,
        )
        sig_bytes = signer.sign(sig_string.encode("utf-8"))
        # Tamper with the signature
        tampered = bytes([b ^ 0xFF for b in sig_bytes])
        sig_b64 = base64.urlsafe_b64encode(tampered).decode("ascii").rstrip("=")

        header = (
            f'Signature keyId="{key_id}",'
            f'headers="(created) (expires) (key-id) (request-target)",'
            f'signature="{sig_b64}",'
            f'created="{created}",'
            f'expires="{expires}"'
        )
        with pytest.raises(ValueError, match="verification failed"):
            verify_signature(header, "GET", "/test")

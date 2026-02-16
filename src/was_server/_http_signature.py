"""Cavage draft-12 HTTP Signature verification with Digital Bazaar (key-id) extension.

Server-side counterpart to the client's signing logic. Parses the Authorization header,
extracts the Ed25519 public key from a did:key identifier, and verifies the signature.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass

import base58
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

_DEFAULT_INCLUDE_HEADERS = [
    "(created)",
    "(expires)",
    "(key-id)",
    "(request-target)",
]

# Multicodec prefix for Ed25519 public keys (0xed 0x01)
_MULTICODEC_ED25519_PUB = b"\xed\x01"

# Regex for parsing Authorization: Signature parameters
_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')


def build_signature_string(
    *,
    method: str,
    path: str,
    created: int,
    expires: int,
    key_id: str,
    include_headers: list[str] | None = None,
) -> str:
    """Build the plaintext string to be signed per Cavage draft-12.

    Each pseudo-header produces one ``name: value`` line; lines are joined with ``\\n``.
    """
    values = {
        "(created)": str(created),
        "(expires)": str(expires),
        "(key-id)": key_id,
        "(request-target)": f"{method.lower()} {path}",
    }
    headers = include_headers or _DEFAULT_INCLUDE_HEADERS
    parts: list[str] = []
    for h in headers:
        if h not in values:
            raise ValueError(f"Unsupported pseudo-header: {h!r}")
        parts.append(f"{h}: {values[h]}")
    return "\n".join(parts)


@dataclass(frozen=True)
class ParsedSignature:
    """Parsed components of an HTTP Signature Authorization header."""

    key_id: str
    controller: str
    headers: list[str]
    signature: bytes
    created: int
    expires: int


def parse_authorization_header(header: str) -> ParsedSignature:
    """Parse an ``Authorization: Signature ...`` header value.

    Raises ``ValueError`` on malformed input.
    """
    if not header.startswith("Signature "):
        raise ValueError("Authorization header must start with 'Signature '")

    params_str = header[len("Signature "):]
    params: dict[str, str] = {}
    for match in _PARAM_RE.finditer(params_str):
        params[match.group(1)] = match.group(2)

    required = {"keyId", "headers", "signature", "created", "expires"}
    missing = required - params.keys()
    if missing:
        raise ValueError(f"Missing signature parameters: {missing}")

    key_id = params["keyId"]

    # Controller is the DID without the fragment
    controller = key_id.split("#")[0]

    headers = params["headers"].split()

    # Re-pad base64url signature for decoding
    sig_b64 = params["signature"]
    sig_b64_padded = sig_b64 + "=" * (-len(sig_b64) % 4)
    signature = base64.urlsafe_b64decode(sig_b64_padded)

    created = int(params["created"])
    expires = int(params["expires"])

    return ParsedSignature(
        key_id=key_id,
        controller=controller,
        headers=headers,
        signature=signature,
        created=created,
        expires=expires,
    )


def extract_public_key(did_key: str) -> Ed25519PublicKey:
    """Extract an Ed25519 public key from a ``did:key:z...`` identifier.

    Handles both ``did:key:z6Mk...`` and ``did:key:z6Mk...#z6Mk...`` formats.

    Raises ``ValueError`` if the DID is malformed or not an Ed25519 key.
    """
    # Strip fragment if present
    did = did_key.split("#")[0]

    if not did.startswith("did:key:z"):
        raise ValueError(f"Expected did:key:z..., got {did_key!r}")

    # Strip "did:key:z" prefix (z = multibase base58btc prefix)
    encoded = did[len("did:key:z"):]
    decoded = base58.b58decode(encoded)

    if not decoded.startswith(_MULTICODEC_ED25519_PUB):
        raise ValueError(f"Expected Ed25519 multicodec prefix (0xed01), got {decoded[:2].hex()}")

    pub_bytes = decoded[len(_MULTICODEC_ED25519_PUB):]
    if len(pub_bytes) != 32:
        raise ValueError(f"Expected 32-byte Ed25519 public key, got {len(pub_bytes)} bytes")

    return Ed25519PublicKey.from_public_bytes(pub_bytes)


def verify_signature(authorization: str, method: str, path: str) -> ParsedSignature:
    """Verify an HTTP Signature Authorization header.

    Returns the parsed signature on success.
    Raises ``ValueError`` on any verification failure.
    """
    parsed = parse_authorization_header(authorization)

    # Check expiration
    now = int(time.time())
    if parsed.expires < now:
        raise ValueError("Signature has expired")

    # Extract public key from keyId
    public_key = extract_public_key(parsed.key_id)

    # Rebuild the signature string
    sig_string = build_signature_string(
        method=method,
        path=path,
        created=parsed.created,
        expires=parsed.expires,
        key_id=parsed.key_id,
        include_headers=parsed.headers,
    )

    # Verify
    try:
        public_key.verify(parsed.signature, sig_string.encode("utf-8"))
    except InvalidSignature:
        raise ValueError("Signature verification failed")  # noqa: B904

    return parsed

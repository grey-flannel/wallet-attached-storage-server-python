from __future__ import annotations

import re
import uuid

_URN_UUID_RE = re.compile(r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def is_urn_uuid(value: str) -> bool:
    """Return True if *value* is a valid ``urn:uuid:`` string."""
    return bool(_URN_UUID_RE.match(value))


def parse_urn_uuid(value: str) -> uuid.UUID:
    """Extract the UUID object from a ``urn:uuid:`` string.

    Raises ``ValueError`` if *value* is not a valid urn:uuid.
    """
    if not is_urn_uuid(value):
        raise ValueError(f"Invalid urn:uuid: {value!r}")
    return uuid.UUID(value[9:])


def make_urn_uuid(u: uuid.UUID | None = None) -> str:
    """Create a ``urn:uuid:`` string.

    If *u* is ``None``, a new random (v4) UUID is generated.
    """
    if u is None:
        u = uuid.uuid4()
    return f"urn:uuid:{u}"

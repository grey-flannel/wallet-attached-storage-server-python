"""Tests for URN UUID utility functions."""

from __future__ import annotations

import uuid

import pytest

from was_server._urn_uuid import is_urn_uuid, make_urn_uuid, parse_urn_uuid


class TestIsUrnUuid:
    def test_valid(self) -> None:
        assert is_urn_uuid("urn:uuid:f47ac10b-58cc-4372-a567-0e02b2c3d479") is True

    def test_uppercase(self) -> None:
        assert is_urn_uuid("urn:uuid:F47AC10B-58CC-4372-A567-0E02B2C3D479") is True

    def test_missing_prefix(self) -> None:
        assert is_urn_uuid("f47ac10b-58cc-4372-a567-0e02b2c3d479") is False

    def test_empty(self) -> None:
        assert is_urn_uuid("") is False


class TestParseUrnUuid:
    def test_valid(self) -> None:
        result = parse_urn_uuid("urn:uuid:f47ac10b-58cc-4372-a567-0e02b2c3d479")
        assert result == uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid urn:uuid"):
            parse_urn_uuid("not-a-urn")


class TestMakeUrnUuid:
    def test_with_uuid(self) -> None:
        u = uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")
        assert make_urn_uuid(u) == "urn:uuid:f47ac10b-58cc-4372-a567-0e02b2c3d479"

    def test_without_uuid_generates(self) -> None:
        result = make_urn_uuid()
        assert result.startswith("urn:uuid:")
        assert is_urn_uuid(result)

"""Tests for lib.session_id.sanitize"""
import pytest

from lib.session_id import sanitize


def test_normal_uuid_passthrough():
    sid = "550e8400-e29b-41d4-a716-446655440000"
    assert sanitize(sid) == sid


def test_alphanumeric_passthrough():
    assert sanitize("abc123") == "abc123"


def test_underscore_dash_passthrough():
    assert sanitize("test_session-1") == "test_session-1"


def test_path_traversal_hashed():
    result = sanitize("../etc/passwd")
    assert "/" not in result and ".." not in result
    assert len(result) == 16


def test_special_chars_hashed():
    result = sanitize("session with spaces!")
    assert all(c in "0123456789abcdef" for c in result)
    assert len(result) == 16


def test_empty_string_raises():
    with pytest.raises(ValueError):
        sanitize("")


def test_too_long_hashed():
    long_id = "a" * 100
    result = sanitize(long_id)
    assert len(result) == 16


def test_deterministic_hash():
    assert sanitize("foo bar") == sanitize("foo bar")


def test_different_inputs_different_hash():
    assert sanitize("foo bar") != sanitize("foo baz")

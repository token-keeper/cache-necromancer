from lib.mask import mask_sid


def test_mask_short_uuid_prefix():
    """36자 UUID → 첫 8자만 노출."""
    sid = "1a6f51ab-49db-4284-84e5-0fc1e951782d"
    assert mask_sid(sid) == "1a6f51ab"


def test_mask_short_id_passthrough_when_le_8():
    """이미 8자 이하면 그대로 (해시 결과 등)."""
    assert mask_sid("abc12345") == "abc12345"
    assert mask_sid("abcd") == "abcd"


def test_mask_empty_returns_question():
    """sentinel '?' 입력 또는 빈 값 → '?' 그대로."""
    assert mask_sid("?") == "?"
    assert mask_sid("") == "?"


def test_mask_is_deterministic():
    assert mask_sid("foobar1234567890") == mask_sid("foobar1234567890")


def test_mask_does_not_leak_full_sid():
    sid = "1a6f51ab-49db-4284-84e5-0fc1e951782d"
    masked = mask_sid(sid)
    assert sid[8:] not in masked

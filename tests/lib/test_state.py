"""Tests for lib.state"""
import fcntl
import json
import threading
import time
from datetime import datetime, timezone

import pytest


@pytest.fixture
def state_module(cn_root, monkeypatch):
    """STATE_DIR을 임시 디렉토리로 override + 모듈 reload."""
    state_dir = cn_root / "state"
    import importlib

    import lib.state

    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", state_dir)
    return lib.state


def test_default_state_has_all_required_fields(state_module):
    now = datetime.now(timezone.utc)
    s = state_module.default_state(
        session_id="abc",
        sid_hash="abc",
        transcript_path="/tmp/abc.jsonl",
        cwd="/tmp",
        now=now,
    )
    required = {
        "session_id", "sid_hash", "transcript_path", "cwd",
        "last_stop_at", "last_user_input_at", "current_turn_started_at",
        "last_fire_at", "refresh_count", "next_refresh_at",
        "imminent_notified", "consecutive_fire_failures",
        "last_fire_reason", "backoff_until",
        "disabled", "disabled_reason", "disabled_at",
        "cache_cold_retries", "created_at",
    }
    assert required.issubset(s.keys())
    assert s["disabled"] is False
    assert s["refresh_count"] == 0
    assert s["cache_cold_retries"] == 0
    assert s["consecutive_fire_failures"] == 0
    assert s["imminent_notified"] is False
    assert s["created_at"] == now.isoformat()


def test_update_state_creates_with_allow_create_true(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "refresh_count": 1},
        allow_create=True,
    )
    path = state_module.STATE_DIR / "abc.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["refresh_count"] == 1


def test_update_state_skips_with_allow_create_false_when_missing(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "refresh_count": 1},
        allow_create=False,
    )
    path = state_module.STATE_DIR / "abc.json"
    assert not path.exists()


def test_update_state_modifies_existing(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "v": 1},
        allow_create=True,
    )
    state_module.update_state(
        "abc",
        lambda x: {**x, "v": x["v"] + 1},
        allow_create=False,
    )
    data = json.loads((state_module.STATE_DIR / "abc.json").read_text())
    assert data["v"] == 2


def test_update_state_mutator_returns_none_aborts_write(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "v": 1},
        allow_create=True,
    )
    state_module.update_state("abc", lambda x: None, allow_create=False)
    data = json.loads((state_module.STATE_DIR / "abc.json").read_text())
    assert data["v"] == 1


def test_atomic_write_no_partial_file_on_concurrent_writes(state_module):
    """동시 쓰기 시 항상 valid JSON, lost update 없이 직렬화."""
    errors = []

    def writer(value):
        try:
            for _ in range(20):
                state_module.update_state(
                    "abc",
                    lambda x, v=value: {**x, "session_id": "abc", "value": v},
                    allow_create=True,
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    data = json.loads((state_module.STATE_DIR / "abc.json").read_text())
    assert "value" in data
    assert data["value"] in (0, 1, 2, 3, 4)


def test_lock_timeout_silent_fail(state_module, monkeypatch):
    """다른 프로세스가 락 잡고 있으면 deadline 후 silent return."""
    monkeypatch.setattr(state_module, "STATE_LOCK_DEADLINE", 0.1)

    lock_path = state_module.STATE_DIR / "abc.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    blocker = open(lock_path, "a+")
    fcntl.flock(blocker, fcntl.LOCK_EX)

    try:
        state_module.update_state(
            "abc",
            lambda x: {**x, "session_id": "abc", "v": 1},
            allow_create=True,
        )
        # 락 못 잡았으므로 파일 안 만들어짐
        assert not (state_module.STATE_DIR / "abc.json").exists()
    finally:
        fcntl.flock(blocker, fcntl.LOCK_UN)
        blocker.close()


def test_delete_state(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "v": 1},
        allow_create=True,
    )
    assert (state_module.STATE_DIR / "abc.json").exists()
    state_module.delete_state("abc")
    assert not (state_module.STATE_DIR / "abc.json").exists()


def test_load_state_missing_returns_none(state_module):
    assert state_module.load_state("nonexistent") is None


def test_load_state_existing_returns_dict(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "v": 42},
        allow_create=True,
    )
    s = state_module.load_state("abc")
    assert s["v"] == 42


def test_load_all_states_returns_list(state_module):
    state_module.update_state("a", lambda x: {**x, "session_id": "a", "v": 1}, allow_create=True)
    state_module.update_state("b", lambda x: {**x, "session_id": "b", "v": 2}, allow_create=True)
    states = state_module.load_all_states()
    assert len(states) == 2
    values = {s["v"] for s in states}
    assert values == {1, 2}


def test_load_all_states_skips_corrupt(state_module):
    state_module.update_state("a", lambda x: {**x, "session_id": "a", "v": 1}, allow_create=True)
    (state_module.STATE_DIR / "corrupt.json").write_text("{invalid")
    states = state_module.load_all_states()
    # corrupt는 skip, 정상 1개만
    assert len(states) == 1
    assert states[0]["v"] == 1


def test_parse_iso():
    assert state_module_iso_helper() == datetime(2026, 5, 12, 14, 30, 0, tzinfo=timezone.utc)


def state_module_iso_helper():
    from lib.state import parse_iso
    return parse_iso("2026-05-12T14:30:00+00:00")


def test_parse_iso_none():
    from lib.state import parse_iso
    assert parse_iso(None) is None

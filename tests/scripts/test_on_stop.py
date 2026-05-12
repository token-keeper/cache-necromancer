"""Tests for scripts/on_stop.py"""
import io
import json
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def stop_module(cn_root, monkeypatch):
    import importlib
    # state / logger 모두 CN_ROOT 적용
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import lib.logger
    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)

    sys.path.insert(0, str(cn_root.parent.parent))  # 안전망
    import scripts.on_stop as mod
    importlib.reload(mod)
    return mod


def _stdin_with(payload: dict) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


def test_on_stop_creates_state(stop_module, monkeypatch):
    payload = {
        "session_id": "abc123",
        "transcript_path": "/tmp/abc123.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "Stop",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_stop.spawn_daemon_if_needed") if False else patch.dict("os.environ"):
        with patch("daemon.spawn.spawn_daemon_if_needed"):
            assert stop_module.main() == 0

    from lib.state import load_state
    s = load_state("abc123")
    assert s is not None
    assert s["session_id"] == "abc123"
    assert s["last_stop_at"] is not None
    assert s["next_refresh_at"] is not None
    assert s["current_turn_started_at"] is None
    assert s["imminent_notified"] is False


def test_on_stop_silent_on_invalid_json(stop_module, monkeypatch):
    """stdin이 invalid JSON이어도 exit 0."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    with patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0


def test_on_stop_silent_when_missing_session_id(stop_module, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _stdin_with({"hook_event_name": "Stop"}))
    with patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0


def test_on_stop_logs_user_turn_when_transcript_has_usage(
    stop_module, monkeypatch, cn_root
):
    """transcript에 assistant usage 있고 current_turn_started_at 있으면 log_user_turn 호출."""
    sid = "abc123"
    state_dir = cn_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    # 기존 state — current_turn_started_at 채워둠 (진짜 user turn 종료 상황)
    initial = {
        "session_id": sid,
        "sid_hash": sid,
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
        "last_stop_at": None,
        "last_user_input_at": "2026-05-12T13:00:00+00:00",
        "current_turn_started_at": "2026-05-12T13:00:30+00:00",
        "last_fire_at": "2026-05-12T12:55:00+00:00",  # turn 시작 전 fire → after_fire=True
        "refresh_count": 0,
        "next_refresh_at": None,
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": "2026-05-12T12:00:00+00:00",
    }
    (state_dir / f"{sid}.json").write_text(json.dumps(initial))

    payload = {
        "session_id": sid,
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    fake_usage = {"cache_read_input_tokens": 45000, "input_tokens": 5, "output_tokens": 10}

    with patch(
        "scripts.on_stop.extract_last_turn_usage",
        return_value=fake_usage,
    ), patch("scripts.on_stop.log_user_turn") as mock_log, \
       patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0

    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs["sid_hash"] == sid
    assert kwargs["usage"] == fake_usage
    assert kwargs["after_fire"] is True


def test_on_stop_skips_user_turn_log_when_no_prev_turn(stop_module, monkeypatch):
    """현재 turn이 없는 (current_turn_started_at=None) Stop은 user_turn log 안 함."""
    payload = {
        "session_id": "fresh",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    fake_usage = {"cache_read_input_tokens": 100}

    with patch(
        "scripts.on_stop.extract_last_turn_usage",
        return_value=fake_usage,
    ), patch("scripts.on_stop.log_user_turn") as mock_log, \
       patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0

    mock_log.assert_not_called()


def test_on_stop_after_fire_false_when_fire_after_turn_start(
    stop_module, monkeypatch, cn_root
):
    """last_fire_at이 current_turn_started_at 이후면 after_fire=False."""
    sid = "abc999"
    state_dir = cn_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    initial = {
        "session_id": sid,
        "sid_hash": sid,
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
        "last_stop_at": None,
        "last_user_input_at": "2026-05-12T13:00:00+00:00",
        "current_turn_started_at": "2026-05-12T13:00:00+00:00",
        "last_fire_at": "2026-05-12T13:05:00+00:00",  # turn 시작 후 fire → after_fire=False
        "refresh_count": 0,
        "next_refresh_at": None,
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": "2026-05-12T12:00:00+00:00",
    }
    (state_dir / f"{sid}.json").write_text(json.dumps(initial))

    payload = {
        "session_id": sid,
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    fake_usage = {"cache_read_input_tokens": 1000}

    with patch(
        "scripts.on_stop.extract_last_turn_usage",
        return_value=fake_usage,
    ), patch("scripts.on_stop.log_user_turn") as mock_log, \
       patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0

    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["after_fire"] is False


def test_on_stop_recovers_after_state_corruption(stop_module, monkeypatch, cn_root):
    """corrupt state가 있어도 hook은 silent recovery."""
    sid = "abc123"
    state_dir = cn_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{sid}.json").write_text("{invalid")

    payload = {
        "session_id": sid,
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("daemon.spawn.spawn_daemon_if_needed"):
        assert stop_module.main() == 0
    from lib.state import load_state
    s = load_state(sid)
    assert s is not None
    assert s["last_stop_at"] is not None

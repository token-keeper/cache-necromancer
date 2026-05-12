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

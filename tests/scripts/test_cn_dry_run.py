"""Tests for scripts/cn_dry_run.py"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def dry_module(cn_root, monkeypatch):
    import importlib
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import scripts.cn_dry_run as mod
    importlib.reload(mod)
    return mod


def test_dry_run_no_sessions(dry_module, capsys, monkeypatch):
    monkeypatch.setattr(
        dry_module, "_resolve_root", lambda: dry_module.Path("/tmp/nope")
    )
    with patch("scripts.cn_dry_run.load_all_states", return_value=[]):
        assert dry_module.main() == 0
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert "추적 세션이 없습니다" in out or "no sessions" in out.lower()


def test_dry_run_lists_sessions_with_next_refresh(dry_module, capsys):
    now = datetime.now(timezone.utc)
    state = {
        "session_id": "abc12345",
        "sid_hash": "abc12345",
        "transcript_path": "/t",
        "cwd": "/t",
        "last_stop_at": now.isoformat(),
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
        "refresh_count": 1,
        "next_refresh_at": (now + timedelta(minutes=5)).isoformat(),
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": now.isoformat(),
    }
    with patch("scripts.cn_dry_run.load_all_states", return_value=[state]):
        assert dry_module.main() == 0
    out = capsys.readouterr().out
    assert "abc12345" in out
    assert "will fire at" in out.lower() or "will fire" in out
    assert "--resume" in out
    assert "--fork-session" in out
    assert "--no-session-persistence" in out


def test_dry_run_marks_disabled_sessions(dry_module, capsys):
    now = datetime.now(timezone.utc)
    state = {
        "session_id": "bad",
        "sid_hash": "bad",
        "transcript_path": "/t",
        "cwd": "/t",
        "last_stop_at": None,
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
        "refresh_count": 0,
        "next_refresh_at": None,
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": "auth_error",
        "backoff_until": None,
        "disabled": True,
        "disabled_reason": "auth_error",
        "disabled_at": now.isoformat(),
        "cache_cold_retries": 0,
        "created_at": now.isoformat(),
    }
    with patch("scripts.cn_dry_run.load_all_states", return_value=[state]):
        assert dry_module.main() == 0
    out = capsys.readouterr().out
    assert "DISABLED" in out
    assert "auth_error" in out
    # disabled 세션은 will fire / command 출력 안 함
    assert "will fire" not in out.lower()


def test_dry_run_shows_mode_and_command_line(dry_module, capsys):
    now = datetime.now(timezone.utc)
    state = {
        "session_id": "sess1",
        "sid_hash": "sess1",
        "transcript_path": "/t",
        "cwd": "/Users/test/projects/x",
        "last_stop_at": now.isoformat(),
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
        "refresh_count": 0,
        "next_refresh_at": (now + timedelta(minutes=10)).isoformat(),
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": now.isoformat(),
    }
    with patch("scripts.cn_dry_run.load_all_states", return_value=[state]):
        with patch.dict("os.environ", {}, clear=False):
            assert dry_module.main() == 0
    out = capsys.readouterr().out
    assert "mode:" in out
    assert "/Users/test/projects/x" in out  # cwd 표시

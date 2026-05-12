"""Tests for scripts/cn_status.py"""
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def status_module(cn_root, monkeypatch):
    import importlib
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import lib.logger
    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)

    import scripts.cn_status as mod
    importlib.reload(mod)
    return mod


def test_status_no_sessions(status_module, capsys, monkeypatch):
    """세션 없는 빈 상태에서도 정상 출력."""
    monkeypatch.setattr(status_module, "_resolve_root", lambda: status_module.Path("/tmp/nonexistent"))
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "cache-necromancer 상태" in out
    assert "데몬: 종료됨" in out
    assert "추적 세션: 0개" in out


def test_status_shows_active_session(status_module, capsys, monkeypatch):
    from datetime import datetime, timezone

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
        "refresh_count": 2,
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
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "abc12345" in out
    assert "refresh_count: 2" in out
    assert "next_refresh:" in out


def test_status_marks_current_session(status_module, capsys, monkeypatch):
    now = datetime.now(timezone.utc)
    state = {
        "session_id": "abc",
        "sid_hash": "abc",
        "transcript_path": "/t",
        "cwd": "/t",
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
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "(this)" in out


def test_status_shows_disabled_session(status_module, capsys):
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
        "consecutive_fire_failures": 5,
        "last_fire_reason": "auth_error",
        "backoff_until": None,
        "disabled": True,
        "disabled_reason": "auth_error",
        "disabled_at": "2026-05-12T14:00:00+00:00",
        "cache_cold_retries": 0,
        "created_at": "2026-05-12T12:00:00+00:00",
    }
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "DISABLED" in out
    assert "auth_error" in out


def test_status_shows_daemon_alive(status_module, capsys, monkeypatch):
    with patch("scripts.cn_status.is_daemon_alive", return_value=True), \
         patch("scripts.cn_status.load_all_states", return_value=[]), \
         patch("scripts.cn_status.Path.read_text", return_value='{"pid": 12345, "started": "Mon May 12 13:00:00 2026"}'):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "데몬: 살아있음" in out
    assert "12345" in out

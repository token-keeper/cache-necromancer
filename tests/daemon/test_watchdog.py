"""Tests for daemon.watchdog — fire→Stop 누락 복구."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from lib.config import Config


def _make_state(**overrides):
    base = {
        "session_id": "abc",
        "sid_hash": "abc",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
        "last_stop_at": None,
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
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
        "created_at": "2026-05-12T13:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_watchdog_noop_when_next_refresh_at_present():
    """next_refresh_at 있으면 정상 상태 — 복구 안 함."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now + timedelta(minutes=30)).isoformat(),
        last_fire_at=(now - timedelta(seconds=200)).isoformat(),
    )
    with patch("daemon.watchdog.update_state") as mock_update:
        result = watchdog.watchdog_check(s, now, Config())
    mock_update.assert_not_called()
    assert result is False


def test_watchdog_noop_when_last_fire_at_missing():
    """last_fire_at 없으면 watchdog 대상 아님."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(next_refresh_at=None, last_fire_at=None)
    with patch("daemon.watchdog.update_state") as mock_update:
        watchdog.watchdog_check(s, now, Config())
    mock_update.assert_not_called()


def test_watchdog_waits_inside_threshold():
    """fire 후 watchdog_seconds 이내면 아직 복구 안 함."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=None,
        last_fire_at=(now - timedelta(seconds=60)).isoformat(),  # 60s < 120s
    )
    with patch("daemon.watchdog.update_state") as mock_update:
        watchdog.watchdog_check(s, now, Config())
    mock_update.assert_not_called()


def test_watchdog_recovers_after_threshold():
    """fire 후 watchdog_seconds 초과 시 next_refresh_at 복구 + last_fire_at None."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=None,
        last_fire_at=(now - timedelta(seconds=200)).isoformat(),  # > 120s
        imminent_notified=True,
    )
    with patch("daemon.watchdog.update_state") as mock_update, \
         patch("daemon.watchdog.log_warn") as mock_warn:
        result = watchdog.watchdog_check(s, now, Config())

    assert result is True  # caller가 sessions 재로드 결정에 활용
    mock_warn.assert_called_once()
    assert "watchdog" in mock_warn.call_args.args[0]
    mock_update.assert_called_once()
    sid_arg, mutator, *_ = mock_update.call_args.args
    assert sid_arg == "abc"
    new_state = mutator(s)
    assert new_state["next_refresh_at"] is not None
    assert new_state["last_fire_at"] is None
    assert new_state["imminent_notified"] is False


def test_watchdog_does_not_increment_refresh_count():
    """이미 한 번 fire한 것이므로 refresh_count 변경 안 함."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=None,
        refresh_count=3,
        last_fire_at=(now - timedelta(seconds=200)).isoformat(),
    )
    with patch("daemon.watchdog.update_state") as mock_update:
        watchdog.watchdog_check(s, now, Config())

    new_state = mock_update.call_args.args[1](s)
    assert new_state["refresh_count"] == 3


def test_watchdog_ignores_malformed_last_fire_at():
    """malformed timestamp 는 _safe_parse_iso 처리 → no-op."""
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(next_refresh_at=None, last_fire_at="not-a-date")
    with patch("daemon.watchdog.update_state") as mock_update:
        watchdog.watchdog_check(s, now, Config())
    mock_update.assert_not_called()


def test_watchdog_update_state_oserror_swallowed():
    from daemon import watchdog

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=None,
        last_fire_at=(now - timedelta(seconds=200)).isoformat(),
    )
    with patch(
        "daemon.watchdog.update_state",
        side_effect=OSError("disk full"),
    ), patch("daemon.watchdog.log_warn") as mock_warn:
        result = watchdog.watchdog_check(s, now, Config())

    assert result is False  # OSError 발생 시 변경 실패 → False
    # watchdog 본체 + update_state 실패 로그 두 줄
    messages = [c.args[0] for c in mock_warn.call_args_list]
    assert any("watchdog" in m and "fire→Stop" in m for m in messages)
    assert any("update_state failed" in m for m in messages)

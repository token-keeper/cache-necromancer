"""Tests for daemon.poller (notify 모드)"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

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


def test_is_refresh_candidate_disabled_returns_false():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(disabled=True, next_refresh_at=(now - timedelta(minutes=1)).isoformat())
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_no_next_refresh_at():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(next_refresh_at=None)
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_future_next_refresh_at():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(next_refresh_at=(now + timedelta(minutes=10)).isoformat())
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_past_next_refresh_at_passes():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
    )
    assert is_refresh_candidate(s, now, Config()) is True


def test_is_refresh_candidate_max_count_reached():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        refresh_count=10,
    )
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_backoff_until_in_future():
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        backoff_until=(now + timedelta(minutes=2)).isoformat(),
    )
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_current_turn_started_blocks():
    """사용자 turn 진행 중이면 fire 후보 아님."""
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        current_turn_started_at=(now - timedelta(seconds=5)).isoformat(),
    )
    assert is_refresh_candidate(s, now, Config()) is False


def test_is_refresh_candidate_interactive_quiet_window_blocks():
    """사용자 input 후 30초 이내면 fire 후보 아님 (rate limit 완화)."""
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(seconds=10)).isoformat(),
    )
    assert is_refresh_candidate(s, now, Config()) is False


def test_min_next_fire_in_returns_max_when_no_candidates():
    from daemon.poller import min_next_fire_in

    now = datetime.now(timezone.utc)
    config = Config()
    assert min_next_fire_in([], now, config) == config.advanced.daemon_poll_max_seconds


def test_min_next_fire_in_picks_smallest_future():
    from daemon.poller import min_next_fire_in

    now = datetime.now(timezone.utc)
    s1 = _make_state(next_refresh_at=(now + timedelta(seconds=30)).isoformat())
    s2 = _make_state(next_refresh_at=(now + timedelta(seconds=120)).isoformat())
    result = min_next_fire_in([s1, s2], now, Config())
    assert 25 <= result <= 35


def test_handle_session_notify_mode_emits_alarm():
    """notify 모드: 후보 도달 시 알림 + imminent_notified=True."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="notify")

    with patch("daemon.poller.notifier.notify") as mock_notify, \
         patch("daemon.poller.update_state") as mock_update:
        poller.handle_session(s, now, config)
        mock_notify.assert_called_once()
        mock_update.assert_called_once()
        # imminent_notified=True 로 업데이트
        mutator = mock_update.call_args.args[1]
        result = mutator(s)
        assert result["imminent_notified"] is True


def test_handle_session_notify_mode_skips_when_already_notified():
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=True,  # 이미 알림 보냄
    )
    config = Config(mode="notify")

    with patch("daemon.poller.notifier.notify") as mock_notify, \
         patch("daemon.poller.update_state") as mock_update:
        poller.handle_session(s, now, config)
        mock_notify.assert_not_called()
        mock_update.assert_not_called()


def test_handle_session_not_candidate_imminent_threshold():
    """후보 아닌데 next_refresh_at - 5min 이내면 임박 알림."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    # next_refresh_at이 미래지만 5분 이내 (interactive quiet window는 통과하도록 시간 조정)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now + timedelta(minutes=3)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="notify")

    with patch("daemon.poller.notifier.notify") as mock_notify, \
         patch("daemon.poller.update_state") as mock_update:
        poller.handle_session(s, now, config)
        # 임박 알림 발생
        mock_notify.assert_called_once()


def test_all_stale_for():
    from daemon.poller import all_stale_for

    now = datetime.now(timezone.utc)
    s_fresh = _make_state(last_stop_at=(now - timedelta(minutes=5)).isoformat())
    s_stale = _make_state(last_stop_at=(now - timedelta(hours=2)).isoformat())
    assert all_stale_for([s_stale], minutes=60, now=now) is True
    assert all_stale_for([s_fresh, s_stale], minutes=60, now=now) is False
    assert all_stale_for([], minutes=60, now=now) is False  # 빈 리스트는 stale 아님

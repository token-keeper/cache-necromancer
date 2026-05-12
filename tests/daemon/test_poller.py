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


def test_handle_session_candidate_delegates_to_execute_mode():
    """후보 도달 시 scheduler.execute_mode 로 위임 (mode 분기는 scheduler 담당)."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="notify")

    with patch("daemon.poller.scheduler.execute_mode") as mock_exec:
        poller.handle_session(s, now, config)
        mock_exec.assert_called_once_with(s, config)


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


def test_handle_session_hybrid_mode_delegates_to_execute_mode():
    """hybrid 모드도 scheduler.execute_mode 로 위임 (Phase 2b부터 실제 동작)."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="hybrid")

    with patch("daemon.poller.scheduler.execute_mode") as mock_exec:
        poller.handle_session(s, now, config)
        mock_exec.assert_called_once_with(s, config)


def test_handle_session_auto_mode_delegates_to_execute_mode():
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="auto")

    with patch("daemon.poller.scheduler.execute_mode") as mock_exec:
        poller.handle_session(s, now, config)
        mock_exec.assert_called_once_with(s, config)


def test_handle_session_not_candidate_does_not_call_execute_mode():
    """후보 아니면 execute_mode 호출 안 됨 (imminent 분기로만 흐름)."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now + timedelta(minutes=30)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=True,
    )
    config = Config(mode="auto")

    with patch("daemon.poller.scheduler.execute_mode") as mock_exec:
        poller.handle_session(s, now, config)
        mock_exec.assert_not_called()


def test_is_refresh_candidate_malformed_next_refresh_at_skips():
    """MAJOR 3 회귀 가드: corrupt timestamp가 있어도 예외 전파 안 됨."""
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(next_refresh_at="not-a-timestamp")
    # ValueError 없이 False 반환
    assert is_refresh_candidate(s, now, Config()) is False


def test_min_next_fire_in_skips_malformed():
    from daemon.poller import min_next_fire_in

    now = datetime.now(timezone.utc)
    s1 = _make_state(next_refresh_at="bogus")
    s2 = _make_state(next_refresh_at=(now + timedelta(seconds=30)).isoformat())
    config = Config()
    # malformed는 skip하고 정상 세션 기반으로 계산
    result = min_next_fire_in([s1, s2], now, config)
    assert 25 <= result <= 35


def test_all_stale_for_malformed_timestamp():
    from daemon.poller import all_stale_for

    now = datetime.now(timezone.utc)
    s = _make_state(last_stop_at="bogus", last_user_input_at=None)
    # malformed → None 취급 → stale 아님 (신규 세션 보호)
    assert all_stale_for([s], minutes=60, now=now) is False


def test_is_refresh_candidate_no_last_user_input_passes_quiet_window():
    """absent last_user_input_at은 interactive quiet window 우회 OK (절대 차단 아님)."""
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=None,
    )
    assert is_refresh_candidate(s, now, Config()) is True


def test_is_refresh_candidate_no_current_turn_passes():
    """absent current_turn_started_at은 차단 안 됨 (None=idle 의미)."""
    from daemon.poller import is_refresh_candidate

    now = datetime.now(timezone.utc)
    s = _make_state(
        next_refresh_at=(now - timedelta(minutes=1)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        current_turn_started_at=None,
    )
    assert is_refresh_candidate(s, now, Config()) is True


def test_handle_session_imminent_update_state_oserror_swallowed():
    """MAJOR 회귀 가드: update_state OSError가 poll loop 죽이지 않음 (imminent 분기)."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s = _make_state(
        sid_hash="abc",
        next_refresh_at=(now + timedelta(minutes=3)).isoformat(),
        last_user_input_at=(now - timedelta(minutes=10)).isoformat(),
        imminent_notified=False,
    )
    config = Config(mode="notify")

    with patch("daemon.poller.notifier.notify"), \
         patch("daemon.poller.update_state", side_effect=OSError("disk full")), \
         patch("daemon.poller.log_warn") as mock_warn:
        poller.handle_session(s, now, config)
        mock_warn.assert_called_once()
        assert "update_state failed" in mock_warn.call_args.args[0]


def test_postpone_all_skips_malformed_timestamp_and_logs():
    """MINOR 회귀 가드: _postpone_all이 _safe_parse_iso 경유 — corrupt timestamp 시 log_warn."""
    from daemon import poller

    s = _make_state(sid_hash="abc", next_refresh_at="bogus")

    def fake_update(sid, mutator, allow_create=False):
        # 실제 동작처럼 mutator를 state에 적용 (반환값은 검증하지 않음)
        return mutator(s)

    with patch("daemon.poller.update_state", side_effect=fake_update) as mock_update, \
         patch("daemon.poller.log_warn") as mock_warn:
        poller._postpone_all([s], minutes=5)
        mock_update.assert_called_once()
        # _safe_parse_iso가 malformed 경고를 한 줄 남김
        assert any(
            "malformed next_refresh_at" in c.args[0] for c in mock_warn.call_args_list
        )


def test_postpone_all_update_state_oserror_swallowed():
    """MAJOR 회귀 가드: postpone 중 update_state OSError가 loop를 죽이지 않음."""
    from daemon import poller

    now = datetime.now(timezone.utc)
    s1 = _make_state(sid_hash="a", next_refresh_at=(now + timedelta(minutes=10)).isoformat())
    s2 = _make_state(sid_hash="b", next_refresh_at=(now + timedelta(minutes=20)).isoformat())

    with patch("daemon.poller.update_state", side_effect=OSError("disk full")) as mock_update, \
         patch("daemon.poller.log_warn") as mock_warn:
        # 첫 세션에서 OSError 났어도 두 번째 세션도 시도
        poller._postpone_all([s1, s2], minutes=5)
        assert mock_update.call_count == 2
        assert mock_warn.call_count == 2

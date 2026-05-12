"""Tests for daemon.scheduler (execute_mode + sleep_with_cancel)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.config import Config


def _make_state(**overrides):
    base = {
        "session_id": "720506ac-f9b9-4d14-9c44-70c70a85472a",
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


# ---------- execute_mode: notify ----------

def test_execute_mode_notify_emits_alarm_and_marks():
    """notify 모드: 알림 + imminent_notified=True."""
    from daemon import scheduler

    s = _make_state(imminent_notified=False)
    config = Config(mode="notify")

    with patch("daemon.scheduler.notifier.notify") as mock_notify, \
         patch("daemon.scheduler.update_state") as mock_update, \
         patch("daemon.scheduler.refresh.fire") as mock_fire:
        scheduler.execute_mode(s, config)

    mock_notify.assert_called_once()
    mock_update.assert_called_once()
    mock_fire.assert_not_called()
    new_state = mock_update.call_args.args[1](s)
    assert new_state["imminent_notified"] is True


def test_execute_mode_notify_update_state_oserror_swallowed_and_logged():
    """notify 모드 imminent_notified 마킹 시 OSError 흡수 + log_warn 한 줄.

    MINOR 회귀 가드: 다른 callsite와 동일하게 log_warn 패턴 유지.
    """
    from daemon import scheduler

    s = _make_state(imminent_notified=False)
    config = Config(mode="notify")

    with patch("daemon.scheduler.notifier.notify"), \
         patch(
             "daemon.scheduler.update_state",
             side_effect=OSError("disk full"),
         ), \
         patch("daemon.scheduler.log_warn") as mock_warn:
        scheduler.execute_mode(s, config)

    mock_warn.assert_called_once()
    assert "notify mark update_state failed" in mock_warn.call_args.args[0]


def test_execute_mode_notify_skips_when_already_notified():
    from daemon import scheduler

    s = _make_state(imminent_notified=True)
    config = Config(mode="notify")

    with patch("daemon.scheduler.notifier.notify") as mock_notify, \
         patch("daemon.scheduler.update_state") as mock_update:
        scheduler.execute_mode(s, config)

    mock_notify.assert_not_called()
    mock_update.assert_not_called()


# ---------- execute_mode: auto ----------

def test_execute_mode_auto_calls_fire_and_handler():
    from daemon import scheduler
    from daemon.refresh import FireReason, FireResult

    s = _make_state()
    config = Config(mode="auto")
    result = FireResult(success=True, reason=FireReason.OK, cache_read=100)

    with patch("daemon.scheduler.refresh.fire", return_value=result) as mock_fire, \
         patch("daemon.scheduler.handler.handle_fire_result") as mock_handle, \
         patch("daemon.scheduler.notifier.notify") as mock_notify:
        scheduler.execute_mode(s, config)

    mock_fire.assert_called_once_with(s, config)
    mock_handle.assert_called_once_with(s, result, config)
    mock_notify.assert_not_called()


# ---------- execute_mode: hybrid ----------

def test_execute_mode_hybrid_warns_then_fires_when_not_cancelled():
    from daemon import scheduler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(sid_hash="abc", last_user_input_at=None)
    config = Config(mode="hybrid")
    result = FireResult(success=True, reason=FireReason.OK, cache_read=100)
    fresh = _make_state(sid_hash="abc")

    with patch("daemon.scheduler.notifier.notify") as mock_notify, \
         patch("daemon.scheduler.sleep_with_cancel", return_value=False), \
         patch("daemon.scheduler.load_state", return_value=fresh), \
         patch("daemon.scheduler.refresh.fire", return_value=result) as mock_fire, \
         patch("daemon.scheduler.handler.handle_fire_result") as mock_handle:
        scheduler.execute_mode(s, config)

    mock_notify.assert_called_once()
    mock_fire.assert_called_once_with(fresh, config)
    mock_handle.assert_called_once_with(fresh, result, config)


def test_execute_mode_hybrid_cancelled_skips_fire():
    from daemon import scheduler

    s = _make_state(sid_hash="abc")
    config = Config(mode="hybrid")

    with patch("daemon.scheduler.notifier.notify"), \
         patch("daemon.scheduler.sleep_with_cancel", return_value=True), \
         patch("daemon.scheduler.refresh.fire") as mock_fire, \
         patch("daemon.scheduler.handler.handle_fire_result") as mock_handle:
        scheduler.execute_mode(s, config)

    mock_fire.assert_not_called()
    mock_handle.assert_not_called()


def test_execute_mode_hybrid_state_deleted_during_wait_skips_fire():
    """hybrid wait 중 세션이 삭제되면 fire 안 함."""
    from daemon import scheduler

    s = _make_state(sid_hash="abc")
    config = Config(mode="hybrid")

    with patch("daemon.scheduler.notifier.notify"), \
         patch("daemon.scheduler.sleep_with_cancel", return_value=False), \
         patch("daemon.scheduler.load_state", return_value=None), \
         patch("daemon.scheduler.refresh.fire") as mock_fire:
        scheduler.execute_mode(s, config)

    mock_fire.assert_not_called()


def test_execute_mode_hybrid_disabled_during_wait_skips_fire():
    """MAJOR 회귀 가드: hybrid wait 중 세션이 disabled로 변하면 fire 금지."""
    from daemon import scheduler

    s = _make_state(sid_hash="abc")
    config = Config(mode="hybrid")
    fresh = _make_state(
        sid_hash="abc", disabled=True, disabled_reason="auth_error"
    )

    with patch("daemon.scheduler.notifier.notify"), \
         patch("daemon.scheduler.sleep_with_cancel", return_value=False), \
         patch("daemon.scheduler.load_state", return_value=fresh), \
         patch("daemon.scheduler.refresh.fire") as mock_fire, \
         patch("daemon.scheduler.handler.handle_fire_result") as mock_handle, \
         patch("daemon.scheduler.log_info") as mock_log:
        scheduler.execute_mode(s, config)

    mock_fire.assert_not_called()
    mock_handle.assert_not_called()
    assert any(
        "cancel-disabled" in c.args[0] for c in mock_log.call_args_list
    )


# ---------- sleep_with_cancel ----------

def test_sleep_with_cancel_returns_false_on_full_duration():
    """user input 변화 없으면 False 반환 (전체 대기 완료)."""
    from daemon import scheduler

    s = _make_state(sid_hash="abc", last_user_input_at=None)

    with patch("daemon.scheduler.time.sleep"), \
         patch(
             "daemon.scheduler.time.monotonic",
             side_effect=[0.0, 0.5, 1.0, 1.5, 2.0],
         ), \
         patch("daemon.scheduler.load_state", return_value=s):
        cancelled = scheduler.sleep_with_cancel(
            1.0, sid_hash="abc", initial_user_input_at=None
        )

    assert cancelled is False


def test_sleep_with_cancel_returns_true_when_user_inputs():
    """대기 중 last_user_input_at이 변화하면 True."""
    from daemon import scheduler

    initial = "2026-05-12T13:00:00+00:00"
    later = "2026-05-12T13:00:30+00:00"
    fresh = _make_state(sid_hash="abc", last_user_input_at=later)

    with patch("daemon.scheduler.time.sleep"), \
         patch(
             "daemon.scheduler.time.monotonic",
             side_effect=[0.0, 0.5, 1.0, 1.5, 2.0],
         ), \
         patch("daemon.scheduler.load_state", return_value=fresh):
        cancelled = scheduler.sleep_with_cancel(
            60.0, sid_hash="abc", initial_user_input_at=initial
        )

    assert cancelled is True


def test_sleep_with_cancel_returns_true_when_session_deleted():
    """대기 중 세션 삭제(load_state None)되면 True."""
    from daemon import scheduler

    with patch("daemon.scheduler.time.sleep"), \
         patch(
             "daemon.scheduler.time.monotonic",
             side_effect=[0.0, 0.5, 1.0, 1.5, 2.0],
         ), \
         patch("daemon.scheduler.load_state", return_value=None):
        cancelled = scheduler.sleep_with_cancel(
            60.0, sid_hash="abc", initial_user_input_at=None
        )

    assert cancelled is True


def test_sleep_with_cancel_initial_none_then_input_arrives():
    """initial None이고 wait 중 사용자가 입력하면 cancel."""
    from daemon import scheduler

    fresh = _make_state(
        sid_hash="abc", last_user_input_at="2026-05-12T13:00:30+00:00"
    )

    with patch("daemon.scheduler.time.sleep"), \
         patch(
             "daemon.scheduler.time.monotonic",
             side_effect=[0.0, 0.5, 1.0, 1.5, 2.0],
         ), \
         patch("daemon.scheduler.load_state", return_value=fresh):
        cancelled = scheduler.sleep_with_cancel(
            60.0, sid_hash="abc", initial_user_input_at=None
        )

    assert cancelled is True


def test_sleep_with_cancel_ignores_same_or_earlier_timestamp():
    """동일/이전 시각은 cancel 아님."""
    from daemon import scheduler

    initial = "2026-05-12T13:01:00+00:00"
    fresh = _make_state(sid_hash="abc", last_user_input_at=initial)

    with patch("daemon.scheduler.time.sleep"), \
         patch(
             "daemon.scheduler.time.monotonic",
             side_effect=[0.0, 0.5, 1.0, 1.5, 2.0],
         ), \
         patch("daemon.scheduler.load_state", return_value=fresh):
        cancelled = scheduler.sleep_with_cancel(
            1.0, sid_hash="abc", initial_user_input_at=initial
        )

    assert cancelled is False

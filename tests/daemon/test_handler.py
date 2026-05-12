"""Tests for daemon.handler (handle_fire_result + _backoff_seconds)."""
import random
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
        "imminent_notified": True,
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


# ---------- _backoff_seconds ----------

def test_backoff_grows_exponentially():
    from daemon.handler import _backoff_seconds

    # jitter 영향 제거 위해 random.random=0.5 고정 → multiplier=0.75
    with patch("daemon.handler.random.random", return_value=0.5):
        b1 = _backoff_seconds(1, base=30.0, cap=1800.0)
        b2 = _backoff_seconds(2, base=30.0, cap=1800.0)
        b3 = _backoff_seconds(3, base=30.0, cap=1800.0)
    # base * 2^(n-1) * 0.75: 22.5, 45, 90
    assert b1 == pytest.approx(22.5)
    assert b2 == pytest.approx(45.0)
    assert b3 == pytest.approx(90.0)


def test_backoff_capped_at_max():
    from daemon.handler import _backoff_seconds

    with patch("daemon.handler.random.random", return_value=1.0):  # multiplier=1.0
        b = _backoff_seconds(20, base=30.0, cap=600.0)
    # exp = min(600, 30 * 2^19) → 600. multiplier=1.0 → 600
    assert b == pytest.approx(600.0)


def test_backoff_jitter_within_range():
    """jitter는 0.5~1.0배 사이로 분포."""
    from daemon.handler import _backoff_seconds

    samples = []
    rng = random.Random(0)
    for _ in range(100):
        with patch("daemon.handler.random.random", return_value=rng.random()):
            samples.append(_backoff_seconds(2, base=30.0, cap=1800.0))
    # 2회 fail = base 60. jitter 범위 30~60
    assert min(samples) >= 30.0 - 0.01
    assert max(samples) <= 60.0 + 0.01


# ---------- handle_fire_result: 성공 ----------

def test_handle_success_advances_scheduler():
    """성공 시 refresh_count++, next_refresh_at, counters 리셋."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(
        refresh_count=2,
        consecutive_fire_failures=3,
        cache_cold_retries=1,
        backoff_until="2026-05-12T15:00:00+00:00",
        imminent_notified=True,
    )
    result = FireResult(success=True, reason=FireReason.OK, cache_read=46115)
    config = Config()

    with patch("daemon.handler.update_state") as mock_update, \
         patch("daemon.handler.log_fire") as mock_log_fire:
        handler.handle_fire_result(s, result, config)

    mock_log_fire.assert_called_once()
    mock_update.assert_called_once()
    sid_arg, mutator, *_ = mock_update.call_args.args
    assert sid_arg == "abc"
    new_state = mutator(s)
    assert new_state["refresh_count"] == 3
    assert new_state["consecutive_fire_failures"] == 0
    assert new_state["cache_cold_retries"] == 0
    assert new_state["backoff_until"] is None
    assert new_state["imminent_notified"] is False
    assert new_state["last_fire_reason"] == "ok"
    assert new_state["next_refresh_at"] is not None
    assert new_state["last_fire_at"] is not None


# ---------- handle_fire_result: AUTH_ERROR ----------

def test_handle_auth_error_calls_disable_session():
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state()
    result = FireResult(success=False, reason=FireReason.AUTH_ERROR)

    with patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_called_once()
    kwargs = mock_disable.call_args.kwargs
    assert kwargs["reason"] == "auth_error"
    assert "인증" in kwargs["message"] or "auth" in kwargs["message"].lower()


# ---------- handle_fire_result: CACHE_COLD ----------

def test_handle_cache_cold_first_retry_sets_backoff():
    """CACHE_COLD 1회: cache_cold_retries++, backoff_until 설정. disable 안 함."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(cache_cold_retries=0)
    result = FireResult(success=False, reason=FireReason.CACHE_COLD)

    with patch("daemon.handler.update_state") as mock_update, \
         patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_not_called()
    mock_update.assert_called_once()
    sid_arg, mutator, *_ = mock_update.call_args.args
    new_state = mutator(s)
    assert new_state["cache_cold_retries"] == 1
    assert new_state["backoff_until"] is not None
    assert new_state["last_fire_reason"] == "cache_cold"


def test_handle_cache_cold_at_max_retries_disables():
    """CACHE_COLD 가 max(기본 2) 도달 시 영구 disable."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(cache_cold_retries=1)  # 이번이 2회째
    result = FireResult(success=False, reason=FireReason.CACHE_COLD)

    with patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.update_state") as mock_update, \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_called_once()
    assert mock_disable.call_args.kwargs["reason"] == "cache_cold_persistent"
    # disable_session이 update_state 호출하므로 외부 update_state는 호출 안 됨
    mock_update.assert_not_called()


# ---------- handle_fire_result: TRANSIENT ----------

def test_handle_transient_increments_failures_and_sets_backoff():
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(consecutive_fire_failures=0)
    result = FireResult(success=False, reason=FireReason.NETWORK_ERROR)

    with patch("daemon.handler.update_state") as mock_update, \
         patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.notifier.notify") as mock_notify, \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_not_called()
    mock_notify.assert_not_called()  # 1회는 아직 알림 없음
    mock_update.assert_called_once()
    new_state = mock_update.call_args.args[1](s)
    assert new_state["consecutive_fire_failures"] == 1
    assert new_state["backoff_until"] is not None
    assert new_state["last_fire_reason"] == "network_error"


def test_handle_transient_three_failures_notifies():
    """3회 연속 실패 시 알림."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(consecutive_fire_failures=2)  # 이번이 3회째
    result = FireResult(success=False, reason=FireReason.TIMEOUT)

    with patch("daemon.handler.update_state"), \
         patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.notifier.notify") as mock_notify, \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_not_called()
    mock_notify.assert_called_once()
    assert "3회" in mock_notify.call_args.args[0] or "3" in mock_notify.call_args.args[0]


def test_handle_transient_five_failures_disables():
    """5회 연속 실패 시 영구 disable."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state(consecutive_fire_failures=4)  # 이번이 5회째
    result = FireResult(success=False, reason=FireReason.NETWORK_ERROR)

    with patch("daemon.handler.update_state"), \
         patch("daemon.handler.disable_session") as mock_disable, \
         patch("daemon.handler.notifier.notify"), \
         patch("daemon.handler.log_fire"):
        handler.handle_fire_result(s, result, Config())

    mock_disable.assert_called_once()
    assert "consecutive_failures" in mock_disable.call_args.kwargs["reason"]


# ---------- log_fire 항상 호출 ----------

def test_log_fire_called_for_every_result():
    """모든 분기에서 log_fire는 한 번 호출."""
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    cases = [
        FireResult(success=True, reason=FireReason.OK, cache_read=100),
        FireResult(success=False, reason=FireReason.AUTH_ERROR),
        FireResult(success=False, reason=FireReason.CACHE_COLD),
        FireResult(success=False, reason=FireReason.NETWORK_ERROR),
        FireResult(success=False, reason=FireReason.TIMEOUT),
        FireResult(success=False, reason=FireReason.PROCESS_ERROR),
        FireResult(success=False, reason=FireReason.BAD_OUTPUT),
    ]
    for r in cases:
        s = _make_state()
        with patch("daemon.handler.update_state"), \
             patch("daemon.handler.disable_session"), \
             patch("daemon.handler.notifier.notify"), \
             patch("daemon.handler.log_fire") as mock_log:
            handler.handle_fire_result(s, r, Config())
            mock_log.assert_called_once()


# ---------- update_state OSError 흡수 ----------

def test_handle_success_update_state_oserror_swallowed():
    from daemon import handler
    from daemon.refresh import FireReason, FireResult

    s = _make_state()
    result = FireResult(success=True, reason=FireReason.OK, cache_read=100)

    with patch(
        "daemon.handler.update_state",
        side_effect=OSError("disk full"),
    ), patch("daemon.handler.log_fire"), \
       patch("daemon.handler.log_warn") as mock_warn:
        handler.handle_fire_result(s, result, Config())

    mock_warn.assert_called_once()
    assert "handle_fire_result" in mock_warn.call_args.args[0]

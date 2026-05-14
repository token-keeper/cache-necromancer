"""Tests for daemon.refresh (fire 호출 + FireReason 분기)."""
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.config import Config


def _make_state(**overrides):
    base = {
        "session_id": "720506ac-f9b9-4d14-9c44-70c70a85472a",
        "sid_hash": "abc",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/Users/brody/projects/test",
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


# ---------- enum / 상수 정의 ----------

def test_fire_reason_enum_values():
    from daemon.refresh import FireReason

    assert FireReason.OK.value == "ok"
    assert FireReason.CACHE_COLD.value == "cache_cold"
    assert FireReason.NETWORK_ERROR.value == "network_error"
    assert FireReason.AUTH_ERROR.value == "auth_error"
    assert FireReason.PROCESS_ERROR.value == "process_error"
    assert FireReason.TIMEOUT.value == "timeout"
    assert FireReason.BAD_OUTPUT.value == "bad_output"


def test_transient_and_permanent_reasons():
    from daemon.refresh import (
        FireReason,
        PERMANENT_REASONS,
        TRANSIENT_REASONS,
    )

    assert PERMANENT_REASONS == {FireReason.AUTH_ERROR}
    assert TRANSIENT_REASONS == {
        FireReason.NETWORK_ERROR,
        FireReason.TIMEOUT,
        FireReason.PROCESS_ERROR,
        FireReason.BAD_OUTPUT,
    }


def test_auth_error_patterns_lowercase():
    """패턴은 lowercase로 정의 — stderr.lower() 매칭 위해."""
    from daemon.refresh import AUTH_ERROR_PATTERNS

    for p in AUTH_ERROR_PATTERNS:
        assert p == p.lower()
    # 핵심 패턴 포함 확인
    joined = " ".join(AUTH_ERROR_PATTERNS)
    for keyword in ("authentication", "unauthorized", "api key", "credential"):
        assert keyword in joined


def test_auth_patterns_exclude_bare_forbidden():
    """MINOR 회귀 가드: 'forbidden' 단독 패턴은 false positive 위험으로 제외."""
    from daemon.refresh import AUTH_ERROR_PATTERNS

    assert "forbidden" not in AUTH_ERROR_PATTERNS


def test_fire_result_defaults():
    from daemon.refresh import FireReason, FireResult

    r = FireResult(success=True, reason=FireReason.OK)
    assert r.cache_read == 0
    assert r.cache_create == 0
    assert r.input_tokens == 0
    assert r.output_tokens == 0
    assert r.model is None
    assert r.raw_stdout == ""


# ---------- fire() 분기 ----------

def _ok_stdout(cache_read: int = 46115) -> str:
    return json.dumps({
        "usage": {
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": 0,
            "input_tokens": 5,
            "output_tokens": 3,
        },
        "modelUsage": {"claude-opus-4-7": {}},
    })


def test_fire_ok_with_cache_read():
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout=_ok_stdout(46115), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is True
    assert result.reason is refresh.FireReason.OK
    assert result.cache_read == 46115
    assert result.input_tokens == 5
    assert result.output_tokens == 3
    assert result.model == "claude-opus-4-7"


def test_fire_cache_cold_when_cache_read_zero():
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout=_ok_stdout(0), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.CACHE_COLD
    assert result.cache_read == 0


def test_fire_bad_output_on_invalid_json():
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout="not-json", stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT
    assert "not-json" in result.raw_stdout


@pytest.mark.parametrize("payload", ["42", '"hello"', "null"])
def test_fire_bad_output_when_top_level_not_object_or_list(payload):
    """MAJOR 회귀 가드: JSON top-level이 dict/list가 아니면 BAD_OUTPUT.

    list는 별도 result-element 추출 분기로 처리 — 그 케이스는 아래 list 전용
    테스트가 커버. 여기는 dict/list 둘 다 아닌 숫자/문자열/null만 검증.
    """
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout=payload, stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT


# ---------- list 응답 처리 (claude CLI ≥2.1.x) ----------

def _list_stdout_with_result(cache_read: int = 20009, *, extras=None) -> str:
    """실제 claude -p --output-format json 응답을 축약한 형태.

    type="system" (init) → "assistant" → "result" (usage). probe 로 캡처한
    실제 형식 기반. extras 는 result element 앞/뒤로 끼울 dict 들.
    """
    result_elem = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 1000,
        "session_id": "abc",
        "total_cost_usd": 0.01,
        "usage": {
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": 0,
            "input_tokens": 5,
            "output_tokens": 3,
        },
        "modelUsage": {"claude-opus-4-7[1m]": {"inputTokens": 5}},
    }
    messages = [
        {"type": "system", "subtype": "init", "cwd": "/tmp"},
        {"type": "assistant", "message": {"id": "msg_1"}},
        result_elem,
    ]
    if extras:
        messages.extend(extras)
    return json.dumps(messages)


def test_fire_ok_with_list_response_picks_result_element():
    """MAJOR 회귀 가드: claude CLI 2.1.x 의 list 응답에서 result element 추출."""
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout=_list_stdout_with_result(20009), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is True
    assert result.reason is refresh.FireReason.OK
    assert result.cache_read == 20009
    assert result.input_tokens == 5
    assert result.output_tokens == 3
    assert result.model == "claude-opus-4-7[1m]"


def test_fire_cache_cold_with_list_response_and_zero_cache_read():
    """list 응답인데 result.usage.cache_read=0 → CACHE_COLD."""
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout=_list_stdout_with_result(0), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.CACHE_COLD


def test_fire_bad_output_when_list_empty():
    """빈 list → result element 없음 → BAD_OUTPUT."""
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout="[]", stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT


def test_fire_bad_output_when_list_has_no_result_element():
    """list 에 type='result' 없으면 BAD_OUTPUT — 비정상 응답."""
    from daemon import refresh

    s = _make_state()
    payload = json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {}},
    ])
    proc = MagicMock(returncode=0, stdout=payload, stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT


def test_fire_picks_last_result_when_multiple():
    """안전 가드: list 안에 type='result' 가 여러 개면 마지막(final)을 사용."""
    from daemon import refresh

    s = _make_state()
    messages = [
        {"type": "system"},
        {
            "type": "result",
            "usage": {"cache_read_input_tokens": 111, "input_tokens": 1, "output_tokens": 1},
        },
        {"type": "assistant"},
        {
            "type": "result",
            "usage": {"cache_read_input_tokens": 999, "input_tokens": 2, "output_tokens": 4},
            "modelUsage": {"final-model": {}},
        },
    ]
    proc = MagicMock(returncode=0, stdout=json.dumps(messages), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is True
    assert result.cache_read == 999
    assert result.model == "final-model"


def test_fire_bad_output_when_list_contains_non_dict_items():
    """list 안에 dict 아닌 element 가 섞여있어도 무시하고 result 찾기 시도."""
    from daemon import refresh

    s = _make_state()
    payload = "[1, 2, 3]"
    proc = MagicMock(returncode=0, stdout=payload, stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT


@pytest.mark.parametrize("usage_value", [[], "string", 42, [{"a": 1}]])
def test_fire_bad_output_when_usage_not_mapping(usage_value):
    """MAJOR 회귀 가드: usage가 dict 아니면 BAD_OUTPUT (.get() AttributeError 차단)."""
    from daemon import refresh

    s = _make_state()
    payload = json.dumps({"usage": usage_value})
    proc = MagicMock(returncode=0, stdout=payload, stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.BAD_OUTPUT


def test_fire_handles_missing_usage_as_cache_cold():
    """usage 키가 아예 없으면 cache_read=0 → CACHE_COLD (스키마 안전 fallback)."""
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(returncode=0, stdout='{"modelUsage": {}}', stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.reason is refresh.FireReason.CACHE_COLD


def test_fire_handles_malformed_modelusage_silently():
    """modelUsage가 dict 아니어도 fire는 OK 분기 진행, model=None."""
    from daemon import refresh

    s = _make_state()
    payload = json.dumps({
        "usage": {"cache_read_input_tokens": 100, "input_tokens": 1, "output_tokens": 1},
        "modelUsage": "not-a-dict",
    })
    proc = MagicMock(returncode=0, stdout=payload, stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is True
    assert result.reason is refresh.FireReason.OK
    assert result.cache_read == 100
    assert result.model is None


def test_fire_auth_error_pattern_in_stderr():
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(
        returncode=1,
        stdout="",
        stderr="Error: API key is invalid or expired token",
    )
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.AUTH_ERROR


def test_fire_network_error_when_no_auth_pattern():
    from daemon import refresh

    s = _make_state()
    proc = MagicMock(
        returncode=1, stdout="", stderr="connection refused (ECONNREFUSED)",
    )
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.NETWORK_ERROR


def test_fire_timeout():
    from daemon import refresh

    s = _make_state()
    with patch(
        "daemon.refresh.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
    ):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.TIMEOUT


def test_fire_process_error_filenotfound():
    from daemon import refresh

    s = _make_state()
    with patch(
        "daemon.refresh.subprocess.run",
        side_effect=FileNotFoundError("claude: not found"),
    ):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.PROCESS_ERROR
    assert "not found" in result.raw_stdout


def test_fire_process_error_permission():
    from daemon import refresh

    s = _make_state()
    with patch(
        "daemon.refresh.subprocess.run",
        side_effect=PermissionError("denied"),
    ):
        result = refresh.fire(s, Config())

    assert result.success is False
    assert result.reason is refresh.FireReason.PROCESS_ERROR


def test_fire_invokes_claude_with_expected_args():
    """cmd 인자 + cwd + timeout 검증."""
    from daemon import refresh

    s = _make_state(cwd="/Users/brody/projects/vdit")
    proc = MagicMock(returncode=0, stdout=_ok_stdout(), stderr="")
    with patch("daemon.refresh.subprocess.run", return_value=proc) as mock_run:
        refresh.fire(s, Config())

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--resume" in cmd
    assert s["session_id"] in cmd
    assert "--fork-session" in cmd
    assert "--no-session-persistence" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd
    assert kwargs["cwd"] == "/Users/brody/projects/vdit"
    assert kwargs["timeout"] == 120
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    # stdin=DEVNULL 회귀 가드: 부모 stdin 상속 차단 — manual fire 시 "no stdin
    # data received" 워닝 제거 + 데몬 호출에서는 영향 없음.
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_fire_stderr_truncated_to_500_chars():
    """긴 stderr는 raw_stdout 500자로 절단 — log 폭주 방지."""
    from daemon import refresh

    s = _make_state()
    long_err = "E" * 5000
    proc = MagicMock(returncode=1, stdout="", stderr=long_err)
    with patch("daemon.refresh.subprocess.run", return_value=proc):
        result = refresh.fire(s, Config())

    assert len(result.raw_stdout) == 500


# ---------- disable_session ----------

def test_disable_session_marks_state_disabled():
    from daemon import refresh

    s = _make_state(sid_hash="abc", disabled=False)
    with patch("daemon.refresh.update_state") as mock_update, \
         patch("daemon.refresh.notifier.notify") as mock_notify:
        refresh.disable_session(s, reason="auth_error", message="❌ 인증 실패")

    mock_update.assert_called_once()
    sid_arg, mutator, *_ = mock_update.call_args.args
    assert sid_arg == "abc"
    new_state = mutator(s)
    assert new_state["disabled"] is True
    assert new_state["disabled_reason"] == "auth_error"
    assert "disabled_at" in new_state
    assert new_state["disabled_at"] is not None
    assert new_state["next_refresh_at"] is None
    assert new_state["last_fire_reason"] == "auth_error"
    mock_notify.assert_called_once()


def test_disable_session_can_skip_notify():
    from daemon import refresh

    s = _make_state(sid_hash="abc")
    with patch("daemon.refresh.update_state"), \
         patch("daemon.refresh.notifier.notify") as mock_notify:
        refresh.disable_session(
            s, reason="cache_cold", message="이건 안 보냄", notify=False
        )

    mock_notify.assert_not_called()


def test_disable_session_update_state_oserror_swallowed_and_skips_notify():
    """MAJOR 회귀 가드: update_state OSError 시 예외 흡수 + notify 스킵.

    저장 실패하면 사용자에게 "비활성화됨" 알림 보내지 않아야 함 — 다음
    poll cycle에서 재시도되므로 알림 폭주/오인 방지.
    """
    from daemon import refresh

    s = _make_state(sid_hash="abc")
    with patch(
        "daemon.refresh.update_state",
        side_effect=OSError("disk full"),
    ), patch("daemon.refresh.notifier.notify") as mock_notify, \
       patch("daemon.refresh.log_warn") as mock_warn:
        # 예외 전파 없이 종료
        refresh.disable_session(s, reason="auth_error", message="❌")

    mock_warn.assert_called_once()
    assert "disable_session update_state failed" in mock_warn.call_args.args[0]
    # 저장 실패 → notify 도 발사하지 않음 (사용자 오인 방지)
    mock_notify.assert_not_called()

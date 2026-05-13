"""Tests for scripts/cn_status.py (v0.2.0 — dry-run 흡수 포함)"""
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


def _base_state(**overrides) -> dict:
    """공통 fixture — overrides 로 일부 키만 바꿔 사용."""
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
    state.update(overrides)
    return state


def test_status_no_sessions(status_module, capsys, monkeypatch):
    """세션 없는 빈 상태 — 모든 섹션이 빈 메시지로 출력."""
    monkeypatch.setattr(
        status_module, "_resolve_root", lambda: status_module.Path("/tmp/nonexistent")
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "cache-necromancer 상태" in out
    assert "■ 데몬" in out
    assert "종료됨" in out
    assert "■ 세션 (active 0, disabled 0)" in out
    assert "추적 중인 세션 없음" in out
    assert "■ 다음 fire 시뮬레이션" in out
    assert "active 세션 없음" in out
    assert "■ 최근 24h fires" in out


def test_status_shows_active_session_summary(status_module, capsys):
    state = _base_state(refresh_count=2)
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "[abc12345]" in out
    assert "next " in out
    # 디폴트 max_refresh_count=10 — refresh 분모 함께 표시
    assert "refresh 2/10" in out
    assert "idle" in out


def test_status_in_turn_marker(status_module, capsys):
    """current_turn_started_at 있으면 idle 대신 in turn 표시."""
    now = datetime.now(timezone.utc)
    state = _base_state(current_turn_started_at=now.isoformat())
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "in turn" in out
    assert "· idle" not in out


def test_status_marks_current_session(status_module, capsys, monkeypatch):
    state = _base_state(session_id="abc", sid_hash="abc")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "(this)" in out


def test_status_shows_disabled_session(status_module, capsys):
    state = _base_state(
        session_id="bad",
        sid_hash="bad",
        next_refresh_at=None,
        consecutive_fire_failures=5,
        last_fire_reason="auth_error",
        disabled=True,
        disabled_reason="auth_error",
        disabled_at="2026-05-12T14:00:00+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "DISABLED" in out
    assert "auth_error" in out


def test_status_disabled_session_excluded_from_next_fires(status_module, capsys):
    """disabled 세션은 '다음 fire 시뮬레이션' 섹션에 안 나옴."""
    state = _base_state(
        session_id="bad",
        sid_hash="bad",
        next_refresh_at=None,
        disabled=True,
        disabled_reason="auth_error",
        disabled_at="2026-05-12T14:00:00+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    next_fires_section = out.split("■ 다음 fire 시뮬레이션", 1)[1].split("■ 최근 24h fires", 1)[0]
    assert "command:" not in next_fires_section
    assert "active 세션 없음" in next_fires_section


def test_status_masks_disabled_uuid_session(status_module, capsys):
    """disabled=True 이고 sid_hash 가 UUID 형식인 경우 마스킹 + DISABLED 표시."""
    now = datetime.now(timezone.utc)
    sid = "1a6f51ab-49db-4284-84e5-0fc1e951782d"
    state = _base_state(
        session_id=sid,
        sid_hash=sid,
        next_refresh_at=None,
        last_fire_reason="auth_error",
        disabled=True,
        disabled_reason="auth_error",
        disabled_at=now.isoformat(),
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert sid[8:] not in out
    assert "1a6f51ab" in out
    assert "DISABLED" in out


def test_status_shows_daemon_alive(status_module, capsys):
    with patch("scripts.cn_status.is_daemon_alive", return_value=True), \
         patch("scripts.cn_status.load_all_states", return_value=[]), \
         patch(
             "scripts.cn_status.Path.read_text",
             return_value='{"pid": 12345, "started": "Mon May 12 13:00:00 2026"}',
         ):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "■ 데몬" in out
    assert "살아있음" in out
    assert "12345" in out


def test_status_masks_uuid_session_id_but_keeps_this_marker(
    status_module, capsys, monkeypatch
):
    """UUID 세션의 원본 노출 없이 (this) 마커는 정상 표시."""
    sid = "1a6f51ab-49db-4284-84e5-0fc1e951782d"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
    state = _base_state(
        session_id=sid,
        sid_hash=sid,
        transcript_path="/tmp/x.jsonl",
        cwd="/tmp",
        next_refresh_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert sid[8:] not in out
    assert "1a6f51ab" in out
    assert "(this)" in out


# --- dry-run 흡수 회귀 가드 ----------------------------------------------------


def test_status_shows_next_fire_command_and_cwd(status_module, capsys):
    """'다음 fire 시뮬레이션' 섹션에 실제 호출될 command + cwd 표시."""
    state = _base_state(
        session_id="abc12345-full-session-id-xyz",
        sid_hash="abc12345",
        cwd="/Users/test/projects/x",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    # build_fire_command argv 확인 (실제 호출 명령)
    assert "--resume" in out
    assert "--fork-session" in out
    assert "--no-session-persistence" in out
    # cwd 표시
    assert "/Users/test/projects/x" in out
    # MAJOR 회귀 가드: full session_id 가 그대로 노출되면 안 됨
    assert "abc12345-full-session-id-xyz" not in out
    assert "<sid:abc12345>" in out


def test_status_next_fire_masks_uuid_session_id(status_module, capsys):
    """UUID 형식 session_id 가 '다음 fire 시뮬레이션' 출력에 원본 그대로 노출 X."""
    sid = "1a6f51ab-49db-4284-84e5-0fc1e951782d"
    state = _base_state(session_id=sid, sid_hash=sid, transcript_path="/tmp/x.jsonl", cwd="/tmp")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert sid[8:] not in out
    assert "1a6f51ab" in out


def test_status_handles_missing_session_id(status_module, capsys):
    """MINOR 회귀 가드: 손상된 state(session_id 누락)에서도 전체가 실패하지 않음."""
    state = _base_state()
    del state["session_id"]
    state["sid_hash"] = "broken1"
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "broken1" in out
    # build_fire_command 가 unknown fallback 또는 mask 처리
    assert "<unknown>" in out or "<sid:" in out


def test_status_shows_mode_label(status_module, capsys):
    """현재 모드 표시 (마지막 줄)."""
    state = _base_state()
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "모드:" in out
    assert "max_refresh:" in out
    assert "/cn:config" in out


def test_status_shows_warnings_for_consec_failures_and_backoff(status_module, capsys):
    """consec_fails > 0 / backoff_until 가 세션 줄 아래 warning 으로 표시."""
    state = _base_state(
        consecutive_fire_failures=3,
        backoff_until="2026-05-13T12:30:00+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "3 consec fails" in out
    assert "backoff until 2026-05-13T12:30:00+00:00" in out


def test_status_shows_last_fire_in_next_fires_section(status_module, capsys):
    """last_fire_at 있으면 '다음 fire 시뮬레이션' 섹션에 표시."""
    last = "2026-05-13T11:25:00+00:00"
    state = _base_state(last_fire_at=last, last_fire_reason="ok")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert f"last_fire: {last}" in out


def test_status_disabled_at_microseconds_truncated(status_module, capsys):
    """disabled_at 의 마이크로초가 출력에서 절단됨."""
    state = _base_state(
        session_id="bad",
        sid_hash="bad",
        next_refresh_at=None,
        disabled=True,
        disabled_reason="auth_error",
        disabled_at="2026-05-13T09:14:35.819981+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert ".819981" not in out
    assert "2026-05-13T09:14:35" in out


def test_status_backoff_until_microseconds_truncated(status_module, capsys):
    """backoff_until 마이크로초가 warning 출력에서 절단됨 (disabled_at 과 일관)."""
    state = _base_state(
        consecutive_fire_failures=2,
        backoff_until="2026-05-13T15:16:41.715567+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert ".715567" not in out
    assert "backoff until 2026-05-13T15:16:41+00:00" in out


def test_trunc_microseconds_fallbacks(status_module):
    """_trunc_microseconds 의 fallback 경로 — None / "" / 비-ISO 입력."""
    fn = status_module._trunc_microseconds
    assert fn(None) == "?"
    assert fn("") == "?"
    # 비-ISO 입력은 원본 그대로 반환 (graceful fallback)
    assert fn("not-a-date") == "not-a-date"
    # 정상 ISO 마이크로초 → 절단
    assert fn("2026-05-13T09:14:35.819981+00:00") == "2026-05-13T09:14:35+00:00"
    # 마이크로초 없는 ISO → 그대로
    assert fn("2026-05-13T09:14:35+00:00") == "2026-05-13T09:14:35+00:00"


def test_status_refresh_count_reflects_config_max(status_module, capsys):
    """refresh count 분모가 실제 config.max_refresh_count 값을 따른다."""
    from lib.config import Config
    state = _base_state(refresh_count=2)
    custom = Config(max_refresh_count=3)
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]), \
         patch("scripts.cn_status.load_config", return_value=custom):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "refresh 2/3" in out
    assert "max_refresh: 3" in out

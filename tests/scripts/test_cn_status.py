"""Tests for scripts/cn_status.py (v0.2.0 — 박스 표 디자인 + hook 기반 turn 0회).

박스 디자인이라 출력에 박스 문자 (┌─│└) 가 섞임. assertion 은 박스 문자 무관한
의미 있는 토큰 (sid, 상태, 마커, 시간 등) 위주.
"""
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
        "last_user_prompt_excerpt": None,
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
    assert "데몬" in out
    assert "종료됨" in out
    assert "세션 (active 0, disabled 0)" in out
    assert "추적 중인 세션 없음" in out
    assert "active 세션 디테일" in out
    assert "active 세션 없음" in out
    assert "최근 24h fires" in out


def test_status_shows_active_session_summary(status_module, capsys):
    state = _base_state(refresh_count=2)
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "abc12345" in out
    # 디폴트 max_refresh_count=10 — refresh 컬럼에 2/10
    assert "2/10" in out
    assert "idle" in out


def test_status_in_turn_marker(status_module, capsys):
    """current_turn_started_at 있으면 상태 컬럼이 in turn."""
    now = datetime.now(timezone.utc)
    state = _base_state(current_turn_started_at=now.isoformat())
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "in turn" in out


def test_status_marks_current_session(status_module, capsys, monkeypatch):
    """CLAUDE_CODE_SESSION_ID 와 매칭되는 세션의 sid 뒤에 * 마커."""
    state = _base_state(session_id="abc", sid_hash="abc")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "abc*" in out


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


def test_status_disabled_excluded_from_active_details(status_module, capsys):
    """disabled 세션은 'active 세션 디테일' 박스에 안 나옴."""
    state = _base_state(
        session_id="bad",
        sid_hash="bad",
        next_refresh_at=None,
        cwd="/tmp/disabled-cwd-marker",
        disabled=True,
        disabled_reason="auth_error",
        disabled_at="2026-05-12T14:00:00+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    details_section = out.split("active 세션 디테일", 1)[1].split("최근 24h fires", 1)[0]
    assert "active 세션 없음" in details_section
    assert "/tmp/disabled-cwd-marker" not in details_section


def test_status_masks_disabled_uuid_session(status_module, capsys):
    """disabled=True + UUID sid 마스킹 + DISABLED 표시."""
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
    assert "데몬" in out
    assert "살아있음" in out
    assert "12345" in out


def test_status_masks_uuid_session_id_but_keeps_this_marker(
    status_module, capsys, monkeypatch
):
    """UUID 세션의 원본 노출 없이 * 마커는 정상."""
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
    assert "1a6f51ab*" in out


def test_status_shows_cwd_in_details(status_module, capsys):
    """active 세션 디테일 박스에 cwd 표시 (70자 이내면 그대로)."""
    state = _base_state(cwd="/Users/test/projects/x")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "cwd:" in out
    assert "/Users/test/projects/x" in out


def test_status_truncates_long_cwd(status_module, capsys):
    """매우 긴 cwd 는 70자 부근에서 ... 으로 truncate."""
    long_cwd = "/Users/test/" + "very_long_directory_name/" * 10
    state = _base_state(cwd=long_cwd)
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert long_cwd not in out  # 전체 그대로 노출되면 안 됨
    assert "..." in out  # truncate 마커


def test_status_shows_last_user_prompt_excerpt(status_module, capsys):
    """state.last_user_prompt_excerpt 가 active 세션 디테일에 표시."""
    state = _base_state(last_user_prompt_excerpt="박스 디자인 변경하자")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "last prompt:" in out
    assert "박스 디자인 변경하자" in out


def test_status_handles_missing_session_id(status_module, capsys):
    """MINOR 회귀 가드: session_id 없는 손상된 state 도 전체 실패 안 함."""
    state = _base_state()
    del state["session_id"]
    state["sid_hash"] = "broken1"
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "broken1" in out


def test_status_shows_mode_label(status_module, capsys):
    """현재 모드 + max_refresh + /cn:config 안내."""
    state = _base_state()
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "모드:" in out
    assert "max_refresh:" in out
    assert "/cn:config" in out


def test_status_shows_warnings_for_consec_failures_and_backoff(status_module, capsys):
    """consec_fails > 0 / backoff_until 가 warning 컬럼에 표시 (시간 부분만)."""
    state = _base_state(
        consecutive_fire_failures=3,
        backoff_until="2026-05-13T12:30:00+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "3 fails" in out
    assert "backoff 12:30:00" in out


def test_status_shows_last_fire_in_details(status_module, capsys):
    """last_fire_at 있으면 active 세션 디테일 박스에 표시."""
    last = "2026-05-13T11:25:00+00:00"
    state = _base_state(last_fire_at=last, last_fire_reason="ok")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "last fire:" in out
    assert last in out


def test_status_disabled_at_short_time(status_module, capsys):
    """disabled_at 출력에서 시간 부분만 (HH:MM:SS), 날짜와 마이크로초 제거."""
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
    assert "09:14:35" in out


def test_status_backoff_until_short_time(status_module, capsys):
    """backoff_until 도 시간 부분만 표시 (disabled_at 과 일관)."""
    state = _base_state(
        consecutive_fire_failures=2,
        backoff_until="2026-05-13T15:16:41.715567+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert ".715567" not in out
    assert "backoff 15:16:41" in out


def test_status_consecutive_failures_prefix_shortened(status_module, capsys):
    """disabled reason 의 consecutive_failures_ prefix 단축."""
    state = _base_state(
        session_id="bad",
        sid_hash="bad",
        next_refresh_at=None,
        disabled=True,
        disabled_reason="consecutive_failures_bad_output",
        disabled_at="2026-05-13T09:14:35+00:00",
    )
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    out = capsys.readouterr().out
    assert "consecutive_failures_" not in out
    assert "bad_output" in out


def test_trunc_microseconds_fallbacks(status_module):
    """_trunc_microseconds 의 fallback 경로 — None / "" / 비-ISO 입력."""
    fn = status_module._trunc_microseconds
    assert fn(None) == "?"
    assert fn("") == "?"
    assert fn("not-a-date") == "not-a-date"
    assert fn("2026-05-13T09:14:35.819981+00:00") == "2026-05-13T09:14:35+00:00"
    assert fn("2026-05-13T09:14:35+00:00") == "2026-05-13T09:14:35+00:00"


def test_short_time_fallbacks(status_module):
    """_short_time helper — None / "" / 비-ISO / 정상 ISO."""
    fn = status_module._short_time
    assert fn(None) == "?"
    assert fn("") == "?"
    assert fn("not-a-date") == "not-a-date"
    assert fn("2026-05-13T09:14:35.819981+00:00") == "09:14:35"
    assert fn("2026-05-13T15:16:41+00:00") == "15:16:41"


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
    assert "2/3" in out
    assert "max_refresh: 3" in out


def test_status_outer_box_responds_to_max_width_env(status_module, capsys, monkeypatch):
    """CN_MAX_WIDTH env var 가 박스 폭에 영향 — 큰 값과 작은 값의 폭이 다름."""
    from lib.box_renderer import display_width
    state = _base_state()

    monkeypatch.setenv("CN_MAX_WIDTH", "150")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    wide = capsys.readouterr().out
    wide_first_line_width = display_width(wide.splitlines()[0])

    monkeypatch.setenv("CN_MAX_WIDTH", "100")
    with patch("scripts.cn_status.is_daemon_alive", return_value=False), \
         patch("scripts.cn_status.load_all_states", return_value=[state]):
        assert status_module.main() == 0
    narrow = capsys.readouterr().out
    narrow_first_line_width = display_width(narrow.splitlines()[0])

    assert wide_first_line_width > narrow_first_line_width

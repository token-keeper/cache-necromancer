# v0.3.0 재작성 중 — Commit 9 에서 lib.state 의존성 제거 후 신규 테스트
"""Tests for scripts/on_status_command.py — cn:status + cn:set 라우팅."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.on_status_command import _route  # noqa: E402

_CN_STATUS = _PROJECT_ROOT / "scripts" / "cn_status.py"
_CN_SET = _PROJECT_ROOT / "scripts" / "cn_set.py"


# ──────────────────────────────────────────────
# _route() 단위 테스트
# ──────────────────────────────────────────────

class TestRoute:
    # ── cn:status ──

    def test_command_name_cn_status(self):
        script, args = _route({"command_name": "cn:status", "prompt": ""})
        assert script == _CN_STATUS
        assert args == []

    def test_command_name_full_cn_status(self):
        script, args = _route({"command_name": "cache-necromancer:cn:status"})
        assert script == _CN_STATUS

    def test_prompt_slash_cn_status(self):
        script, args = _route({"command_name": "", "prompt": "/cn:status"})
        assert script == _CN_STATUS
        assert args == []

    def test_prompt_slash_full_cn_status(self):
        script, args = _route({"prompt": "/cache-necromancer:cn:status"})
        assert script == _CN_STATUS

    # ── cn:set with command_name ──

    def test_command_name_cn_set_with_arg_as_prompt(self):
        """Claude Code 가 command_name='cn:set', prompt='2' (인자만) 로 전달하는 형태."""
        script, args = _route({"command_name": "cn:set", "prompt": "2"})
        assert script == _CN_SET
        assert args == ["2"]

    def test_command_name_cn_set_with_slash_prompt(self):
        """command_name='cn:set', prompt='/cn:set 2' (슬래시 포함) 형태도 허용."""
        script, args = _route({"command_name": "cn:set", "prompt": "/cn:set 2"})
        assert script == _CN_SET
        assert args == ["2"]

    def test_command_name_full_cn_set(self):
        script, args = _route({"command_name": "cache-necromancer:cn:set", "prompt": "3"})
        assert script == _CN_SET
        assert args == ["3"]

    def test_command_name_cn_set_no_prompt(self):
        """인자 없는 /cn:set — args 빈 리스트."""
        script, args = _route({"command_name": "cn:set", "prompt": ""})
        assert script == _CN_SET
        assert args == []

    # ── cn:set with prompt fallback (no command_name) ──

    def test_prompt_slash_cn_set_with_arg(self):
        script, args = _route({"command_name": "", "prompt": "/cn:set 2"})
        assert script == _CN_SET
        assert args == ["2"]

    def test_prompt_slash_cn_set_no_arg(self):
        script, args = _route({"prompt": "/cn:set"})
        assert script == _CN_SET
        assert args == []

    def test_prompt_slash_full_cn_set_with_arg(self):
        script, args = _route({"prompt": "/cache-necromancer:cn:set 5"})
        assert script == _CN_SET
        assert args == ["5"]

    # ── 비매칭 ──

    def test_unrelated_command_name_returns_none(self):
        assert _route({"command_name": "other:cmd", "prompt": ""}) is None

    def test_unrelated_prompt_returns_none(self):
        assert _route({"command_name": "", "prompt": "/something else"}) is None

    def test_empty_returns_none(self):
        assert _route({}) is None

    def test_other_command_name_with_poisoned_prompt_not_routed(self):
        """command_name 이 있으면 그것만으로 판정 — prompt 에 /cn:status 가
        들어가 있어도 fallback 으로 빠지면 안 됨."""
        assert _route({"command_name": "other:cmd", "prompt": "/cn:status"}) is None

    def test_cn_settings_not_routed_to_cn_set(self):
        """토큰 일치 — '/cn:settings ...' 는 cn:set 으로 라우팅하면 안 됨."""
        assert _route({"prompt": "/cn:settings foo"}) is None

    def test_cn_set_prefix_only_not_matched_as_cn_status(self):
        """/cn:set 은 cn:status 로 라우팅하면 안 됨."""
        result = _route({"prompt": "/cn:set 2"})
        assert result is not None
        script, _ = result
        assert script == _CN_SET

    def test_cn_status_not_matched_as_cn_set(self):
        """/cn:status 는 cn:set 으로 라우팅하면 안 됨."""
        result = _route({"prompt": "/cn:status"})
        assert result is not None
        script, _ = result
        assert script == _CN_STATUS


# ──────────────────────────────────────────────
# main() 통합 — subprocess 호출 검증
# ──────────────────────────────────────────────

def _run_main_capturing(stdin_data: dict, monkeypatch):
    """(rc, stdout_str, mock_subprocess) 반환."""
    import io
    from contextlib import redirect_stdout

    import scripts.on_status_command as mod

    fake_result = MagicMock()
    fake_result.stdout = "ok"
    fake_result.returncode = 0
    fake_result.stderr = ""

    buf = io.StringIO()
    with patch.object(mod, "subprocess") as mock_sub, redirect_stdout(buf):
        mock_sub.run.return_value = fake_result
        mock_sub.TimeoutExpired = __import__("subprocess").TimeoutExpired
        with patch("sys.stdin", io.StringIO(json.dumps(stdin_data))):
            rc = mod.main()

    return rc, buf.getvalue(), mock_sub


class TestMainRouting:
    def test_cn_status_command_name_calls_cn_status(self, monkeypatch):
        rc, out, mock_sub = _run_main_capturing(
            {"command_name": "cn:status", "prompt": "", "session_id": "sess1"},
            monkeypatch,
        )
        assert rc == 0
        call_args = mock_sub.run.call_args[0][0]
        assert str(_CN_STATUS) in call_args
        assert "block" in out

    def test_cn_set_command_name_calls_cn_set_with_arg(self, monkeypatch):
        rc, out, mock_sub = _run_main_capturing(
            {"command_name": "cn:set", "prompt": "2", "session_id": "sess1"},
            monkeypatch,
        )
        assert rc == 0
        call_args = mock_sub.run.call_args[0][0]
        assert str(_CN_SET) in call_args
        assert "2" in call_args

    def test_cn_set_prompt_fallback_with_arg(self, monkeypatch):
        rc, out, mock_sub = _run_main_capturing(
            {"command_name": "", "prompt": "/cn:set 2", "session_id": "sess1"},
            monkeypatch,
        )
        assert rc == 0
        call_args = mock_sub.run.call_args[0][0]
        assert str(_CN_SET) in call_args
        assert "2" in call_args

    def test_cn_set_prompt_fallback_no_arg(self, monkeypatch):
        """bare /cn:set — args 없이 cn_set.py 만 호출."""
        rc, out, mock_sub = _run_main_capturing(
            {"prompt": "/cn:set", "session_id": "sess1"},
            monkeypatch,
        )
        assert rc == 0
        call_args = mock_sub.run.call_args[0][0]
        assert str(_CN_SET) in call_args
        # 인자로 "/cn:set" 자체가 전달되면 안 됨
        assert "/cn:set" not in call_args[2:]

    def test_unrelated_prompt_passes_through(self, monkeypatch):
        import io
        from contextlib import redirect_stdout
        import scripts.on_status_command as mod

        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("sys.stdin", io.StringIO(json.dumps({"prompt": "/other:cmd"}))):
                rc = mod.main()
        assert rc == 0
        assert buf.getvalue() == ""

    def test_session_id_propagated_to_env(self, monkeypatch):
        _, _, mock_sub = _run_main_capturing(
            {"command_name": "cn:status", "prompt": "", "session_id": "mysession"},
            monkeypatch,
        )
        env = mock_sub.run.call_args[1]["env"]
        assert env["CLAUDE_CODE_SESSION_ID"] == "mysession"

    def test_cn_settings_not_routed(self, monkeypatch):
        import io
        from contextlib import redirect_stdout
        import scripts.on_status_command as mod

        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("sys.stdin", io.StringIO(json.dumps({"prompt": "/cn:settings foo"}))):
                rc = mod.main()
        assert rc == 0
        assert buf.getvalue() == ""

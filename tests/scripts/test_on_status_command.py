"""Tests for scripts/on_status_command.py — UserPromptExpansion hook for /cn:status.

목적:
  /cn:status 입력 시 hook 이 LLM turn 차단하고 reason 으로 cn_status.py 결과 반환.
  - command_name 매칭 (cn:status / cache-necromancer:cn:status)
  - prompt 문자열 매칭 (fallback)
  - 그 외 입력은 pass-through (출력 없음, exit 0)
  - session_id 환경변수 전파 → cn_status.py subprocess 에 CLAUDE_CODE_SESSION_ID
"""
import io
import json
import sys
from unittest.mock import patch

import pytest


@pytest.fixture
def hook_module(cn_root, monkeypatch):
    import importlib
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import scripts.on_status_command as mod
    importlib.reload(mod)
    return mod


def _stdin_with(payload: dict) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


class _FakeResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_matches_by_command_name_short(hook_module, monkeypatch, capsys):
    """command_name=cn:status 면 매칭 → cn_status.py 호출 + decision=block."""
    payload = {"command_name": "cn:status", "session_id": "abc", "prompt": ""}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run",
               return_value=_FakeResult(stdout="STATUS_OUTPUT")) as run:
        assert hook_module.main() == 0
    out = capsys.readouterr().out
    response = json.loads(out)
    assert response["decision"] == "block"
    assert "STATUS_OUTPUT" in response["reason"]
    # cn_status.py subprocess 호출됐는지 + env 에 session_id 전파됐는지
    assert run.called
    call_kwargs = run.call_args.kwargs
    assert call_kwargs["env"]["CLAUDE_CODE_SESSION_ID"] == "abc"


def test_matches_by_command_name_full_namespace(hook_module, monkeypatch, capsys):
    """plugin namespace 포함한 full command_name 도 매칭."""
    payload = {"command_name": "cache-necromancer:cn:status", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run",
               return_value=_FakeResult(stdout="OK")):
        assert hook_module.main() == 0
    out = capsys.readouterr().out
    assert json.loads(out)["decision"] == "block"


def test_matches_by_prompt_fallback(hook_module, monkeypatch, capsys):
    """command_name 없어도 prompt 문자열로 매칭."""
    payload = {"prompt": "/cn:status", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run",
               return_value=_FakeResult(stdout="OK")):
        assert hook_module.main() == 0
    out = capsys.readouterr().out
    assert json.loads(out)["decision"] == "block"


def test_pass_through_for_unrelated_input(hook_module, monkeypatch, capsys):
    """매칭 안 되는 입력은 stdout 출력 없이 exit 0."""
    payload = {"prompt": "안녕 코드 수정해줘", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run") as run:
        assert hook_module.main() == 0
    out = capsys.readouterr().out
    assert out == ""  # decision JSON 출력 없음
    assert not run.called  # cn_status.py 도 호출 안 됨


def test_pass_through_for_other_slash_commands(hook_module, monkeypatch, capsys):
    """/cn:config 같은 다른 slash command 는 통과."""
    payload = {"command_name": "cn:config", "prompt": "/cn:config", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run") as run:
        assert hook_module.main() == 0
    out = capsys.readouterr().out
    assert out == ""
    assert not run.called


def test_command_name_takes_precedence_over_prompt(hook_module, monkeypatch, capsys):
    """command_name 이 있으면 prompt 의 /cn:status 우연 일치 무시 — false positive 회귀 가드."""
    payload = {
        "command_name": "cn:config",
        "prompt": "/cn:status",  # 모순 입력 — command_name 만 따름
        "session_id": "abc",
    }
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run") as run:
        assert hook_module.main() == 0
    assert capsys.readouterr().out == ""
    assert not run.called


def test_silent_on_invalid_json(hook_module, monkeypatch, capsys):
    """JSON 파싱 실패 시 silent exit 0."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert hook_module.main() == 0
    assert capsys.readouterr().out == ""


def test_handles_subprocess_failure(hook_module, monkeypatch, capsys):
    """cn_status.py 가 non-zero exit + stderr 시에도 reason 에 결과 포함."""
    payload = {"command_name": "cn:status", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    with patch("scripts.on_status_command.subprocess.run",
               return_value=_FakeResult(stdout="partial", stderr="boom", returncode=1)):
        assert hook_module.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "partial" in response["reason"]
    assert "boom" in response["reason"]


def test_handles_subprocess_timeout(hook_module, monkeypatch, capsys):
    """subprocess timeout 시 reason 에 안내 + decision=block 유지."""
    import subprocess
    payload = {"command_name": "cn:status", "session_id": "abc"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))

    def _raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="python3", timeout=10)

    with patch("scripts.on_status_command.subprocess.run", side_effect=_raise_timeout):
        assert hook_module.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["decision"] == "block"
    assert "타임아웃" in response["reason"] or "timeout" in response["reason"].lower()

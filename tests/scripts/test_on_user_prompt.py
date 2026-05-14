"""Tests for scripts/on_user_prompt.py"""
import io
import json
import sys
from datetime import datetime, timezone

import pytest


@pytest.fixture
def user_prompt_module(cn_root, monkeypatch):
    import importlib
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import lib.logger
    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)

    import scripts.on_user_prompt as mod
    importlib.reload(mod)
    return mod


def _stdin_with(payload: dict) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


def test_skips_when_state_missing(user_prompt_module, monkeypatch):
    """allow_create=False라 state 없으면 silent skip."""
    payload = {"session_id": "newSession", "prompt": "hi"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0
    # state 파일 안 만들어짐
    from lib.state import load_state
    assert load_state("newSession") is None


def test_updates_existing_state(user_prompt_module, monkeypatch):
    from lib.state import default_state, update_state, load_state

    sid = "abc"
    update_state(
        sid,
        lambda x: default_state(
            session_id=sid,
            sid_hash=sid,
            transcript_path="/tmp/t.jsonl",
            cwd="/tmp",
            now=datetime.now(timezone.utc),
        ),
        allow_create=True,
    )

    payload = {"session_id": sid, "prompt": "hello"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0

    s = load_state(sid)
    assert s["last_user_input_at"] is not None
    assert s["current_turn_started_at"] is not None


def test_silent_on_invalid_json(user_prompt_module, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert user_prompt_module.main() == 0


# --- v0.2.0: last_user_prompt_excerpt 저장 (cn:status 박스 표 표시용) -----


def _seed_state(sid: str):
    from lib.state import default_state, update_state
    update_state(
        sid,
        lambda x: default_state(
            session_id=sid,
            sid_hash=sid,
            transcript_path="/tmp/t.jsonl",
            cwd="/tmp",
            now=datetime.now(timezone.utc),
        ),
        allow_create=True,
    )


def test_excerpt_saved_for_natural_language(user_prompt_module, monkeypatch):
    """자연어 prompt 의 첫 줄이 state.last_user_prompt_excerpt 로 저장."""
    from lib.state import load_state

    sid = "abc"
    _seed_state(sid)

    payload = {"session_id": sid, "prompt": "박스 디자인 변경하자\n두번째 줄은 무시"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0

    s = load_state(sid)
    assert s["last_user_prompt_excerpt"] == "박스 디자인 변경하자"


def test_excerpt_skips_slash_command(user_prompt_module, monkeypatch):
    """slash command 는 excerpt 저장 안 함."""
    from lib.state import load_state

    sid = "abc"
    _seed_state(sid)

    payload = {"session_id": sid, "prompt": "/cn:status"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0

    s = load_state(sid)
    assert s.get("last_user_prompt_excerpt") is None


def test_excerpt_truncates_long_prompt(user_prompt_module, monkeypatch):
    """80자 초과 prompt 는 ... 으로 truncate."""
    from lib.state import load_state

    sid = "abc"
    _seed_state(sid)

    long_prompt = "x" * 200
    payload = {"session_id": sid, "prompt": long_prompt}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0

    s = load_state(sid)
    excerpt = s["last_user_prompt_excerpt"]
    assert len(excerpt) == 80
    assert excerpt.endswith("...")


def test_excerpt_opt_out_via_env(user_prompt_module, monkeypatch):
    """CN_TRACK_LAST_PROMPT=0 이면 excerpt 저장 안 함."""
    from lib.state import load_state

    sid = "abc"
    _seed_state(sid)

    monkeypatch.setenv("CN_TRACK_LAST_PROMPT", "0")
    payload = {"session_id": sid, "prompt": "이건 저장 안 됨"}
    monkeypatch.setattr(sys, "stdin", _stdin_with(payload))
    assert user_prompt_module.main() == 0

    s = load_state(sid)
    assert s.get("last_user_prompt_excerpt") is None

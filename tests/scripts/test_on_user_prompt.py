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

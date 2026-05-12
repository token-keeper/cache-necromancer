"""Tests for scripts/on_session_end.py"""
import io
import json
import sys
from datetime import datetime, timezone

import pytest


@pytest.fixture
def session_end_module(cn_root, monkeypatch):
    import importlib
    import lib.state
    importlib.reload(lib.state)
    monkeypatch.setattr(lib.state, "STATE_DIR", cn_root / "state")

    import lib.logger
    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)

    import scripts.on_session_end as mod
    importlib.reload(mod)
    return mod


def _stdin_with(payload: dict) -> io.StringIO:
    return io.StringIO(json.dumps(payload))


def test_deletes_existing_state(session_end_module, monkeypatch):
    from lib.state import default_state, update_state, load_state, STATE_DIR

    sid = "abc"
    update_state(
        sid,
        lambda x: default_state(
            session_id=sid,
            sid_hash=sid,
            transcript_path="/t",
            cwd="/t",
            now=datetime.now(timezone.utc),
        ),
        allow_create=True,
    )
    assert (STATE_DIR / f"{sid}.json").exists()

    monkeypatch.setattr(sys, "stdin", _stdin_with({"session_id": sid}))
    assert session_end_module.main() == 0
    assert load_state(sid) is None
    # lock도 정리됨
    assert not (STATE_DIR / f"{sid}.lock").exists()


def test_silent_on_missing_state(session_end_module, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _stdin_with({"session_id": "nonexistent"}))
    assert session_end_module.main() == 0


def test_silent_on_invalid_json(session_end_module, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert session_end_module.main() == 0

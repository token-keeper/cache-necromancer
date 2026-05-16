"""Tests for scripts/on_user_prompt.py (TECH_SPEC §5)."""
import io
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.on_user_prompt import main  # noqa: E402


def _set_stdin(monkeypatch, payload: dict | str | None) -> None:
    if payload is None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
    elif isinstance(payload, str):
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    else:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


class TestResetWakeCount:
    def test_resets_wake_count_to_zero(self, cn_root, monkeypatch):
        sid = "session-abc"
        sh = sanitize(sid)
        # 기존 marker 에 wake_count = 5
        Marker(sid_hash=sh, wake_count=5, latest_fire=12345, last_wake_at=999).save()

        _set_stdin(monkeypatch, {"session_id": sid})
        rc = main()
        assert rc == 0

        loaded = Marker.load(sh)
        assert loaded.wake_count == 0
        # 다른 필드 보존
        assert loaded.latest_fire == 12345
        assert loaded.last_wake_at == 999

    def test_creates_marker_when_missing(self, cn_root, monkeypatch):
        sid = "new-session"
        _set_stdin(monkeypatch, {"session_id": sid})
        rc = main()
        assert rc == 0
        # marker 생성됨 + wake_count = 0
        loaded = Marker.load(sanitize(sid))
        assert loaded.wake_count == 0


class TestEdgeCases:
    def test_no_session_id_returns_silently(self, cn_root, monkeypatch):
        _set_stdin(monkeypatch, {})
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert main() == 0

    def test_invalid_json_returns_silently(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, "not json {")
        assert main() == 0

    def test_session_id_from_env_when_stdin_missing(self, cn_root, monkeypatch):
        sid = "env-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, wake_count=3).save()

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _set_stdin(monkeypatch, "")
        assert main() == 0
        assert Marker.load(sh).wake_count == 0

    def test_marker_save_failure_returns_0(self, cn_root, monkeypatch):
        """save 실패해도 chat 영향 X (exit 0)."""
        sid = "fail-session"
        _set_stdin(monkeypatch, {"session_id": sid})
        from lib.marker import Marker as M

        def bad_save(self):
            raise OSError("simulated")

        monkeypatch.setattr(M, "save", bad_save)
        assert main() == 0

    def test_stdin_session_id_takes_priority_over_env(self, cn_root, monkeypatch):
        """stdin 과 env 둘 다 있으면 stdin 우선 (TECH_SPEC §5)."""
        stdin_sid = "stdin-session"
        env_sid = "env-session"
        # 두 marker 미리 wake_count = 5
        Marker(sid_hash=sanitize(stdin_sid), wake_count=5).save()
        Marker(sid_hash=sanitize(env_sid), wake_count=5).save()

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", env_sid)
        _set_stdin(monkeypatch, {"session_id": stdin_sid})
        assert main() == 0

        # stdin 의 marker 만 reset
        assert Marker.load(sanitize(stdin_sid)).wake_count == 0
        assert Marker.load(sanitize(env_sid)).wake_count == 5

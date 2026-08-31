"""Tests for scripts/on_session_start.py (v0.8.0 clear/compact 소생 억제)."""
import io
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker, marker_dir  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.on_session_start import main  # noqa: E402


def _set_stdin(monkeypatch, payload: dict | str) -> None:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))


class TestSuppressRecord:
    def test_records_suppressed_at_ns(self, cn_root, monkeypatch, capsys):
        sid = "compacting-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, latest_fire=100).save()

        _set_stdin(monkeypatch, {"session_id": sid})
        assert main() == 0

        m = Marker.load(sh)
        assert m.suppressed_at_ns > 0
        assert m.latest_fire == 100  # 기존 필드 보존
        # SessionStart 의 stdout 은 세션 컨텍스트에 주입되므로 출력 금지
        assert capsys.readouterr().out == ""

    def test_creates_marker_when_missing(self, cn_root, monkeypatch):
        sid = "fresh-session"
        sh = sanitize(sid)
        _set_stdin(monkeypatch, {"session_id": sid})
        assert main() == 0
        assert Marker.load(sh).suppressed_at_ns > 0

    def test_session_id_from_env(self, cn_root, monkeypatch):
        sid = "env-session-start"
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _set_stdin(monkeypatch, "")
        assert main() == 0
        assert Marker.load(sanitize(sid)).suppressed_at_ns > 0


class TestNoOpPaths:
    def test_no_session_id_is_noop(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, {})
        assert main() == 0
        d = marker_dir()
        assert not d.exists() or list(d.glob("*.json")) == []

    def test_broken_stdin_is_noop(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, "not json {")
        assert main() == 0

    def test_marker_save_failure_silent(self, cn_root, monkeypatch):
        sid = "save-fail"
        _set_stdin(monkeypatch, {"session_id": sid})

        from lib.marker import Marker as M

        def bad_save(self):
            raise OSError("simulated")

        monkeypatch.setattr(M, "save", bad_save)
        assert main() == 0

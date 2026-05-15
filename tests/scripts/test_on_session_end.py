"""Tests for scripts/on_session_end.py (TECH_SPEC §6)."""
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker, marker_dir, marker_path  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.on_session_end import main  # noqa: E402


def _set_stdin(monkeypatch, payload: dict | str | None) -> None:
    if payload is None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
    elif isinstance(payload, str):
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    else:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


class TestMarkerDelete:
    def test_deletes_current_session_marker(self, cn_root, monkeypatch):
        sid = "ending-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, latest_fire=100).save()
        assert marker_path(sh).exists()

        _set_stdin(monkeypatch, {"session_id": sid})
        assert main() == 0
        assert not marker_path(sh).exists()

    def test_silent_when_no_session_id(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, {})
        assert main() == 0  # 그냥 cleanup 만 시도

    def test_silent_when_marker_missing(self, cn_root, monkeypatch):
        sid = "no-marker-session"
        _set_stdin(monkeypatch, {"session_id": sid})
        assert main() == 0  # idempotent (marker.delete 가 silent)

    def test_session_id_from_env(self, cn_root, monkeypatch):
        sid = "env-session-end"
        sh = sanitize(sid)
        Marker(sid_hash=sh).save()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _set_stdin(monkeypatch, "")
        assert main() == 0
        assert not marker_path(sh).exists()


class TestStaleCleanup:
    def test_cleans_stale_files_older_than_7_days(self, cn_root, monkeypatch):
        d = marker_dir()
        d.mkdir(parents=True, exist_ok=True)
        old = d / "old-stale.json"
        fresh = d / "fresh.json"
        old.write_text("{}", encoding="utf-8")
        fresh.write_text("{}", encoding="utf-8")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))

        _set_stdin(monkeypatch, {})
        main()

        assert not old.exists()
        assert fresh.exists()

    def test_cleanup_runs_even_without_session_id(self, cn_root, monkeypatch):
        """SessionEnd 가 session_id 없이 호출돼도 stale cleanup 진행."""
        d = marker_dir()
        d.mkdir(parents=True, exist_ok=True)
        old = d / "old.json"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (time.time() - 10 * 86400, time.time() - 10 * 86400))

        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, {})
        main()
        assert not old.exists()


class TestErrorPaths:
    def test_invalid_json_returns_0(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, "not json {")
        assert main() == 0

    def test_marker_delete_failure_silent(self, cn_root, monkeypatch):
        sid = "fail-delete"
        _set_stdin(monkeypatch, {"session_id": sid})

        def bad_delete(self):
            raise OSError("simulated")

        from lib.marker import Marker as M
        monkeypatch.setattr(M, "delete", bad_delete)
        assert main() == 0  # warn log + 진행

    def test_cleanup_stale_failure_silent(self, cn_root, monkeypatch):
        """cleanup_stale 자체가 OSError raise 해도 main 은 exit 0 (PRD 불변)."""
        _set_stdin(monkeypatch, {})

        def bad_cleanup(*args, **kwargs):
            raise OSError("simulated cleanup fail")

        monkeypatch.setattr("scripts.on_session_end.cleanup_stale", bad_cleanup)
        assert main() == 0


class TestPriority:
    def test_stdin_session_id_takes_priority_over_env(self, cn_root, monkeypatch):
        """stdin 과 env 둘 다 있으면 stdin 우선 (TECH_SPEC §6)."""
        stdin_sid = "stdin-end"
        env_sid = "env-end"
        Marker(sid_hash=sanitize(stdin_sid)).save()
        Marker(sid_hash=sanitize(env_sid)).save()

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", env_sid)
        _set_stdin(monkeypatch, {"session_id": stdin_sid})
        assert main() == 0

        # stdin 의 marker 만 삭제
        assert not marker_path(sanitize(stdin_sid)).exists()
        assert marker_path(sanitize(env_sid)).exists()

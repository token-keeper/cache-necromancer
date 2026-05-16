"""Tests for scripts/cn_status.py (v0.3.0 — TECH_SPEC §8).

box 출력 detail 보다는 각 세션/설정 상태가 정확히 표시되는지 위주 검증.
"""
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.cn_status import CN_HOOK_MARKER, main  # noqa: E402


def _run_status(monkeypatch=None) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    return buf.getvalue()


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    cr = tmp_path / "fresh_claude"
    cr.mkdir()
    monkeypatch.setenv("CN_CLAUDE_ROOT", str(cr))
    return cr


class TestHeader:
    def test_shows_mode_and_intervals(self, cn_root, isolated_settings, monkeypatch):
        cfg = cn_root / "config.toml"
        cfg.write_text(
            '[general]\nmode = "auto"\nrefresh_interval_minutes = 30\n'
            "max_refresh_count = 7\n",
            encoding="utf-8",
        )
        out = _run_status()
        assert "mode:" in out
        assert "auto" in out
        assert "refresh_interval: 30m" in out
        assert "max_refresh: 7" in out


class TestCurrentSession:
    def test_shows_current_session_marker(
        self, cn_root, isolated_settings, monkeypatch
    ):
        sid = "current-session-id"
        sh = sanitize(sid)
        # marker 미리 만듦
        Marker(
            sid_hash=sh,
            latest_fire=int(time.time() * 1_000_000_000),
            wake_count=2,
            last_wake_at=int(time.time()) - 600,
            session_started_at=int(time.time()) - 3600,
        ).save()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)

        out = _run_status()
        assert "세션 (현재)" in out
        assert "wake/notify count:  2 / 10" in out
        assert "다음 발동 예상" in out
        assert "cache 추정" in out

    def test_no_current_session_when_no_env(
        self, cn_root, isolated_settings, monkeypatch
    ):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()
        # 현재 세션 박스 없음, 다른 세션 박스만
        assert "다른 세션" in out


class TestOtherSessions:
    def test_lists_other_session_markers(
        self, cn_root, isolated_settings, monkeypatch
    ):
        # marker 2개 생성
        Marker(sid_hash=sanitize("session-a"), wake_count=3,
               last_wake_at=int(time.time()) - 300).save()
        Marker(sid_hash=sanitize("session-b"), wake_count=1).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        out = _run_status()
        assert "wake/notify 3/10" in out
        assert "wake/notify 1/10" in out

    def test_empty_when_no_markers(
        self, cn_root, isolated_settings, monkeypatch
    ):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()
        assert "다른 세션" in out
        assert "없음" in out


class TestSettingsStatus:
    def test_hook_registered_via_plugin_manifest(
        self, cn_root, isolated_settings
    ):
        # enabledPlugins 에 cache-necromancer
        sj = isolated_settings / "settings.json"
        sj.write_text(json.dumps({
            "enabledPlugins": {
                "cache-necromancer@cache-necromancer-marketplace": True
            }
        }))
        out = _run_status()
        assert "plugin manifest" in out
        assert "✅" in out

    def test_hook_registered_via_settings_json(
        self, cn_root, isolated_settings
    ):
        sj = isolated_settings / "settings.json"
        sj.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": f"python3 {CN_HOOK_MARKER}"}]}
                ]
            }
        }))
        out = _run_status()
        assert "settings.json (수동 등록)" in out

    def test_hook_not_registered(self, cn_root, isolated_settings):
        # settings.json 없음
        out = _run_status()
        assert "❌ 미등록" in out
        assert "새 chat 세션" in out


class TestDeprecatedConfig:
    def test_warns_about_deprecated_options(self, cn_root, isolated_settings):
        cfg = cn_root / "config.toml"
        cfg.write_text(
            '[general]\nmode = "auto"\n'
            '[refresh]\nprompt = "."\n'
            "[notify]\nterminal_bell = true\n"
            "[advanced]\ndaemon_poll_max_seconds = 30\n",
            encoding="utf-8",
        )
        out = _run_status()
        assert "deprecated v0.2.x config" in out
        assert "refresh.prompt" in out
        assert "notify.terminal_bell" in out
        assert "[advanced]" in out

    def test_no_warning_when_clean_config(self, cn_root, isolated_settings):
        cfg = cn_root / "config.toml"
        cfg.write_text('[general]\nmode = "auto"\n', encoding="utf-8")
        out = _run_status()
        assert "deprecated config: 없음" in out


class TestNotifyModeWarning:
    def test_warns_when_mode_is_notify(self, cn_root, isolated_settings):
        cfg = cn_root / "config.toml"
        cfg.write_text('[general]\nmode = "notify"\n', encoding="utf-8")
        out = _run_status()
        assert "mode=notify — cache 갱신 효과 없음" in out

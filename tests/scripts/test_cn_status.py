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
from lib.mask import mask_sid  # noqa: E402
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
        # marker 미리 만듦 (v0.3.5: 시작/마지막 wake/cache 추정 제거됨)
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
        assert "repeat count:    2 / 10" in out
        assert "다음 발동 예상" in out
        # v0.3.5: 시작 / 마지막 wake/notify / cache 추정 제거됨
        assert "시작:" not in out
        assert "마지막 wake/notify" not in out
        assert "cache 추정" not in out

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
        # marker 2개 생성 — v0.3.5: 중첩 박스로 표시 (sid 가 inner box 제목)
        ts_ns = int(time.time() * 1_000_000_000)
        Marker(
            sid_hash=sanitize("session-a"),
            latest_fire=ts_ns,
            wake_count=3,
            last_prompt="첫 번째 세션 작업 중",
        ).save()
        Marker(
            sid_hash=sanitize("session-b"),
            latest_fire=ts_ns,
            wake_count=1,
            last_prompt="두 번째 세션",
        ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        out = _run_status()
        # outer 박스
        assert "다른 세션" in out
        # inner 박스 본문
        assert "다음:" in out
        assert "마지막:" in out
        # last_prompt 표시 (PRD §8 예외 — single-user alpha)
        assert "첫 번째 세션 작업 중" in out
        assert "두 번째 세션" in out

    def test_other_session_shows_em_dash_when_no_prompt(
        self, cn_root, isolated_settings, monkeypatch
    ):
        """옛 marker (last_prompt 없음) 는 '—' 로 표시 (백워드 호환)."""
        Marker(
            sid_hash=sanitize("legacy-session"),
            latest_fire=int(time.time() * 1_000_000_000),
        ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()
        assert '마지막:  "—"' in out

    def test_other_session_truncated_when_more_than_max(
        self, cn_root, isolated_settings, monkeypatch
    ):
        """OTHER_SESSIONS_MAX_SHOW 초과 시 '... 외 N개' 표시."""
        for i in range(8):
            Marker(
                sid_hash=sanitize(f"sess-{i:02d}"),
                latest_fire=int(time.time() * 1_000_000_000) + i,
            ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()
        # 5개만 표시 + ... 외 3개
        assert "... 외 3개" in out

    def test_other_session_filters_empty_markers(
        self, cn_root, isolated_settings, monkeypatch
    ):
        """v0.3.6: latest_fire == 0 인 빈 marker 는 표시 제외 (noise 방지)."""
        # 의미 있는 marker 1개
        Marker(
            sid_hash=sanitize("active"),
            latest_fire=int(time.time() * 1_000_000_000),
            last_prompt="작업 중",
        ).save()
        # 빈 marker 3개 (latest_fire = 0, last_prompt = "")
        for sid in ("empty-a", "empty-b", "empty-c"):
            Marker(sid_hash=sanitize(sid)).save()

        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()

        # 의미 있는 sid 만 표시
        assert mask_sid(sanitize("active")) in out
        # 빈 marker 의 sid 는 노출 X
        for sid in ("empty-a", "empty-b", "empty-c"):
            assert mask_sid(sanitize(sid)) not in out

    def test_other_session_all_empty_shows_none(
        self, cn_root, isolated_settings, monkeypatch
    ):
        """모든 다른 세션이 빈 marker 면 '없음' 표시."""
        for sid in ("empty-1", "empty-2"):
            Marker(sid_hash=sanitize(sid)).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run_status()
        assert "다른 세션" in out
        assert "없음" in out

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

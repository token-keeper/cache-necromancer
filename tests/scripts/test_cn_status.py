"""Tests for scripts/cn_status.py (v0.3.13).

박스 재구성 + i18n (ko/en/ja/zh) 검증.
"""
import io
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
from scripts.cn_status import main  # noqa: E402


def _run() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    return buf.getvalue()


def _write_config(cn_root: Path, body: str) -> None:
    (cn_root / "config.toml").write_text(body, encoding="utf-8")


# ---------- 기본 라벨 (default en) ----------

class TestDefaultEnglish:
    def test_default_lang_is_english(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "Other sessions" in out
        assert "Status" in out
        # 한글 라벨 없어야 함
        assert "다른 세션" not in out
        assert "상태" not in out

    def test_status_box_contains_mode_and_plugin(self, cn_root, monkeypatch):
        _write_config(cn_root, '[general]\nmode = "auto"\nlanguage = "en"\n')
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "mode:" in out
        assert "auto" in out
        assert "plugin:" in out
        assert "cache-necromancer" in out

    def test_no_hook_registration_check(self, cn_root, monkeypatch):
        """v0.3.13: hook 등록 / deprecated config 검증 제거."""
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "hook 등록" not in out
        assert "deprecated" not in out
        assert "plugin manifest" not in out


# ---------- 현재 세션 ----------

class TestCurrentSession:
    def test_shows_current_session_box(self, cn_root, monkeypatch):
        sid = "current-sid"
        sh = sanitize(sid)
        Marker(
            sid_hash=sh,
            latest_fire=int(time.time() * 1_000_000_000),
            wake_count=2,
        ).save()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')

        out = _run()
        assert "Session (current)" in out
        assert "repeat count" in out
        assert "2 / 10" in out
        assert "next fire" in out


# ---------- 다른 세션 ----------

class TestOtherSessions:
    def test_other_session_shows_next_prompt_cwd(self, cn_root, monkeypatch):
        ts_ns = int(time.time() * 1_000_000_000)
        Marker(
            sid_hash=sanitize("sess-a"),
            latest_fire=ts_ns,
            last_prompt="hello",
            cwd="/Users/foo/projects/proj-x",
        ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')

        out = _run()
        assert "Other sessions" in out
        assert "next fire" in out
        assert "prompt" in out
        assert "cwd" in out
        assert "hello" in out
        assert "/Users/foo/projects/proj-x" in out

    def test_cwd_abbreviated_to_tilde(self, cn_root, monkeypatch):
        home = str(Path.home())
        Marker(
            sid_hash=sanitize("home-sess"),
            latest_fire=int(time.time() * 1_000_000_000),
            cwd=f"{home}/work/proj",
        ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')

        out = _run()
        assert "~/work/proj" in out
        # 절대경로 그대로 X
        assert f"{home}/work/proj" not in out

    def test_cwd_em_dash_when_missing(self, cn_root, monkeypatch):
        Marker(
            sid_hash=sanitize("no-cwd"),
            latest_fire=int(time.time() * 1_000_000_000),
        ).save()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')

        out = _run()
        # cwd: — (정확한 형식)
        assert "cwd:" in out
        assert "—" in out

    def test_filters_stale_markers_past_next_fire(self, cn_root, monkeypatch):
        """v0.3.13: 다음 발동 예상이 과거 (음수) 인 stale 세션은 표시 제외.

        wake cycle 종료된 세션 (max_refresh_count 도달 / chat 종료) 의 노이즈
        제거. cleanup_stale 7d 와 별개 — marker 파일은 유지하고 표시만 차단.
        """
        # 과거 latest_fire — refresh_interval (50m) 후도 이미 한참 전
        stale_ns = int((time.time() - 10 * 3600) * 1_000_000_000)  # 10h ago
        Marker(
            sid_hash=sanitize("stale-sess"),
            latest_fire=stale_ns,
            last_prompt="오래된 작업",
        ).save()
        # 정상 active 세션
        Marker(
            sid_hash=sanitize("live-sess"),
            latest_fire=int(time.time() * 1_000_000_000),
            last_prompt="현재 작업",
        ).save()

        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')
        out = _run()

        assert "현재 작업" in out
        # stale 세션은 박스 자체 노출 X
        assert mask_sid(sanitize("stale-sess")) not in out
        assert "오래된 작업" not in out

    def test_filters_empty_markers(self, cn_root, monkeypatch):
        Marker(
            sid_hash=sanitize("active"),
            latest_fire=int(time.time() * 1_000_000_000),
            last_prompt="x",
        ).save()
        for sid in ("empty-a", "empty-b"):
            Marker(sid_hash=sanitize(sid)).save()

        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')
        out = _run()
        assert mask_sid(sanitize("active")) in out
        for sid in ("empty-a", "empty-b"):
            assert mask_sid(sanitize(sid)) not in out

    def test_no_other_sessions_shows_none(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')
        out = _run()
        assert "Other sessions" in out
        assert "none" in out


# ---------- i18n (ko/ja/zh) ----------

@pytest.mark.parametrize(
    "lang,labels",
    [
        ("ko", ["세션 (현재)", "다른 세션", "상태", "폴더", "mode"]),
        ("en", ["Session (current)", "Other sessions", "Status", "cwd", "mode"]),
        ("ja", ["セッション (現在)", "他のセッション", "状態", "ディレクトリ", "mode"]),
        ("zh", ["会话 (当前)", "其他会话", "状态", "目录", "mode"]),
    ],
)
class TestI18n:
    def test_labels_per_language(self, cn_root, monkeypatch, lang, labels):
        sid = "lang-sid"
        sh = sanitize(sid)
        Marker(
            sid_hash=sh,
            latest_fire=int(time.time() * 1_000_000_000),
        ).save()
        # 다른 세션 1개 (cwd 라벨 노출 위해)
        Marker(
            sid_hash=sanitize("other-x"),
            latest_fire=int(time.time() * 1_000_000_000),
            cwd="/tmp/x",
        ).save()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _write_config(cn_root, f'[general]\nlanguage = "{lang}"\n')

        out = _run()
        for label in labels:
            assert label in out, f"lang={lang} 라벨 '{label}' 누락"


# ---------- notify warning ----------

class TestNotifyWarn:
    def test_notify_mode_shows_warning_en(self, cn_root, monkeypatch):
        _write_config(cn_root, '[general]\nmode = "notify"\nlanguage = "en"\n')
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "mode=notify" in out
        assert "no cache refresh" in out

    def test_notify_mode_shows_warning_ko(self, cn_root, monkeypatch):
        _write_config(cn_root, '[general]\nmode = "notify"\nlanguage = "ko"\n')
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "mode=notify" in out
        assert "cache 갱신 효과 없음" in out

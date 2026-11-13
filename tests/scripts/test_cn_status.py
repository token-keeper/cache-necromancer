"""Tests for scripts/cn_status.py (v0.12.0).

v0.12.0: 자동 깨우기·덮어쓰기·off 상태 + 생존 시각(§3 식) + 옛 설정 한 줄 경고.
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

    def test_status_box_contains_auto_wakes_and_plugin(self, cn_root, monkeypatch):
        _write_config(cn_root, '[general]\nlanguage = "en"\nauto_wakes = 3\n')
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "auto wakes:" in out
        assert "3 per away" in out
        assert "interval 50m · ttl 60m" in out
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
        assert "revived:" in out and "2× (this away)" in out
        # 기본 auto_wakes 2 를 다 썼다 → 0 left, 다음 깨우기 행 없음
        assert "auto · 0 left" in out
        assert "next wake" not in out
        assert "cache until" in out


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
        assert "next wake" in out
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
        """캐시 최대 생존 시각(§3 식)이 이미 지난 stale 세션은 표시 제외."""
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
        ("ko", ["세션 (현재)", "다른 세션", "상태", "폴더", "자동 깨우기", "살림", "자리비움마다 2회"]),
        ("en", ["Session (current)", "Other sessions", "Status", "cwd", "auto wakes", "revived"]),
        ("ja", ["セッション (現在)", "他のセッション", "状態", "ディレクトリ", "自動延長", "蘇生"]),
        ("zh", ["会话 (当前)", "其他会话", "状态", "目录", "自动唤醒", "已复活"]),
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


# ---------- 깨우기 상태 표시 (v0.12.0) ----------

def _current(monkeypatch, **fields) -> None:
    sid = "state-sid"
    Marker(sid_hash=sanitize(sid), **fields).save()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


class TestWakeStateDisplay:
    def test_override_shows_remaining(self, cn_root, monkeypatch):
        _current(monkeypatch, latest_fire=time.time_ns(), wake_count=1,
                 set_budget_remaining=2, set_budget_total=3)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')
        assert "/cn:set override · 2 left" in _run()

    def test_off_shows_off(self, cn_root, monkeypatch):
        _current(monkeypatch, latest_fire=time.time_ns(), wake_off=True,
                 set_budget_remaining=0, set_budget_total=0)
        _write_config(cn_root, '[general]\nlanguage = "en"\n')
        out = _run()
        assert "off (this session)" in out
        assert "next wake" not in out

    def test_auto_disabled_in_status_box(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _write_config(cn_root, '[general]\nlanguage = "ko"\nauto_wakes = 0\n')
        out = _run()
        assert "자동 깨우기:" in out and "꺼짐" in out

    def test_survive_time_uses_latest_fire_formula(self, cn_root, monkeypatch):
        """캐시 최대 = latest_fire + remaining × interval + ttl (§3 식)."""
        from datetime import datetime
        fire = time.time_ns() - 10 * 60 * 1_000_000_000
        _current(monkeypatch, latest_fire=fire)
        _write_config(cn_root, '[general]\nlanguage = "en"\nauto_wakes = 2\n')
        expect = datetime.fromtimestamp(fire / 1e9 + (2 * 50 + 60) * 60).strftime("%H:%M")
        import re
        assert re.search(rf"cache until:\s+{expect}", _run())

    def test_other_session_active_while_cache_alive(self, cn_root, monkeypatch):
        """다른 세션 active = 마지막 Stop + ttl 이 미래. 남은 깨우기가 있어도 만료면 제외
        (깨웠다면 ping turn 의 Stop 이 latest_fire 를 올렸을 것)."""
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        now = time.time_ns()
        Marker(sid_hash=sanitize("alive"), latest_fire=now - 30 * 60 * 1_000_000_000,
               last_prompt="살아있음").save()
        Marker(sid_hash=sanitize("dead"), latest_fire=now - 61 * 60 * 1_000_000_000,
               last_prompt="죽었음").save()
        _write_config(cn_root, '[general]\nlanguage = "en"\nauto_wakes = 2\n')
        out = _run()
        assert "살아있음" in out
        assert "죽었음" not in out

    def test_expired_cache_shows_expired_not_time(self, cn_root, monkeypatch):
        _current(monkeypatch, latest_fire=time.time_ns() - 90 * 60 * 1_000_000_000,
                 set_budget_remaining=3, set_budget_total=3)
        _write_config(cn_root, '[general]\nlanguage = "ko"\n')
        out = _run()
        assert "이미 만료 — 다음 자리비움부터" in out
        assert "다음 깨우기" not in out

    def test_interval_ge_ttl_no_next_wake_and_ttl_only(self, cn_root, monkeypatch):
        """interval ≥ ttl: 깨울 수 없음 — 다음 깨우기 없음, 생존 = Stop + ttl."""
        import re
        from datetime import datetime
        fire = time.time_ns() - 10 * 60 * 1_000_000_000
        _current(monkeypatch, latest_fire=fire)
        _write_config(cn_root, '[general]\nlanguage = "en"\n'
                               'refresh_interval_minutes = 60\ncache_ttl_minutes = 60\n')
        out = _run()
        assert "next wake" not in out
        expect = datetime.fromtimestamp(fire / 1e9 + 60 * 60).strftime("%H:%M")
        assert re.search(rf"cache until:\s+{expect}", out)
        assert "cannot wake (interval ≥ ttl)" in out and "left" not in out  # v0.13.0 D: 횟수 숨김


# ---------- 옛 설정 경고 ----------

class TestObsoleteConfigWarning:
    def test_obsolete_keys_one_line_count(self, cn_root, monkeypatch):
        _write_config(
            cn_root,
            '[general]\nmode = "hybrid"\nmax_refresh_count = 10\nlanguage = "ko"\n'
            '[wake]\narm = "always"\ngrace_seconds = 60\n',
        )
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "무시되는 옛 설정 4개 — /cn:config 저장 시 정리" in out
        # 키 이름은 나열하지 않는다
        assert "general.mode" not in out

    def test_no_warning_with_new_keys(self, cn_root, monkeypatch):
        _write_config(cn_root, '[general]\nauto_wakes = 2\nlanguage = "en"\n')
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        out = _run()
        assert "obsolete" not in out

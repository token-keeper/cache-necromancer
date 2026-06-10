"""Tests for scripts/on_recap.py + hooks/hooks.json 구조 (recap design spec)."""
import io
import json
import sys
from pathlib import Path

import pytest
from freezegun import freeze_time

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_hooks_json() -> dict:
    path = _PROJECT_ROOT / "hooks" / "hooks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_hooks_json_stop_array_has_two_entries():
    """Stop 배열에 sync (on_recap) + async (refresh) 두 hook 등록."""
    data = _load_hooks_json()
    stop = data["hooks"]["Stop"]
    assert len(stop) == 2, f"Stop 배열 객체 2개 기대, 실제 {len(stop)}"


def test_hooks_json_first_stop_is_sync_recap():
    """첫번째 = on_recap.py (sync, asyncRewake X, timeout 5)."""
    data = _load_hooks_json()
    first = data["hooks"]["Stop"][0]["hooks"][0]
    assert "on_recap.py" in first["command"]
    assert first.get("asyncRewake") is not True
    assert first["timeout"] == 5


def test_hooks_json_second_stop_is_async_refresh_unchanged():
    """두번째 = refresh.py (asyncRewake true, timeout 3600) — 기존 그대로."""
    data = _load_hooks_json()
    second = data["hooks"]["Stop"][1]["hooks"][0]
    assert "refresh.py" in second["command"]
    assert second["asyncRewake"] is True
    assert second["timeout"] == 3600


@pytest.fixture
def session_stdin(monkeypatch):
    """stdin JSON 으로 session_id 주입."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sid = "test-recap-sid"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    return sid


@pytest.fixture
def empty_stdin(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


@pytest.fixture
def temp_root(monkeypatch, tmp_path):
    """CN_ROOT 를 tmp_path 로 격리. config.toml 자동 생성됨."""
    monkeypatch.setenv("CN_ROOT", str(tmp_path))
    return tmp_path


def test_main_no_session_id_exits_silently(empty_stdin, capsys):
    """session_id 없으면 stdout empty + exit 0."""
    from scripts.on_recap import main
    rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_main_top_level_exception_silent_fail(session_stdin, capsys, monkeypatch):
    """예상 밖 예외 발생해도 stdout empty + exit 0."""
    def boom(_):
        raise RuntimeError("boom")
    monkeypatch.setattr("scripts.on_recap.sanitize", boom)
    from scripts.on_recap import main
    rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


# ---- 메시지 4 언어 (local time, fire=10:00, cache_ttl=50 → 10:50) ----

@freeze_time("2026-05-23 10:00:00")
def test_recap_message_ko(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "ko"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["systemMessage"] == "🪦 캐시는 10시 50분에 죽어요."


@freeze_time("2026-05-23 10:00:00")
def test_recap_message_en(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 10:50."


@freeze_time("2026-05-23 10:00:00")
def test_recap_message_ja(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "ja"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 キャッシュは10時50分に死にます。"


@freeze_time("2026-05-23 10:00:00")
def test_recap_message_zh(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "zh"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 缓存将在10点50分死亡。"


# ---- 자정 넘김 ----

@freeze_time("2026-05-23 23:55:00")
def test_midnight_rollover_en(session_stdin, temp_root, capsys):
    """fire=23:55, ttl=30 → 00:25"""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 30\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 00:25."


@freeze_time("2026-05-23 23:55:00")
def test_midnight_rollover_ko(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 30\nlanguage = "ko"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 캐시는 0시 25분에 죽어요."


# ---- ttl default (60 min) ----

@freeze_time("2026-05-23 08:37:00")
def test_recap_uses_cache_ttl_not_refresh_interval(session_stdin, temp_root, capsys):
    """refresh_interval (wake 주기) 와 cache_ttl (cache 만료) 분리 검증.

    fire=08:37, refresh_interval=50 (무시), cache_ttl=60 → 09:37 표시.
    """
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\n'
        'refresh_interval_minutes = 50\n'
        'cache_ttl_minutes = 60\n'
        'language = "ko"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 캐시는 9시 37분에 죽어요."


@freeze_time("2026-05-23 10:00:00")
def test_recap_default_ttl_is_60_min(session_stdin, temp_root, capsys):
    """config 에 cache_ttl 미지정 시 default=60 → 11:00 표시."""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 11:00."


# ---- language fallback ----

@freeze_time("2026-05-23 10:00:00")
def test_recap_default_language_en(session_stdin, temp_root, capsys):
    """config 에 language 없으면 'en'."""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 10:50."


@freeze_time("2026-05-23 10:00:00")
def test_recap_invalid_language_falls_back_to_en(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "xx"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 10:50."


# ---- ttl 가드 ----

@pytest.mark.parametrize("ttl", [0, -1, -100])
def test_invalid_ttl_silent_fail(session_stdin, temp_root, capsys, ttl):
    (temp_root / "config.toml").write_text(
        f'[general]\nmode = "auto"\ncache_ttl_minutes = {ttl}\n'
        'language = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_config_invalid_toml_falls_back_to_default(
    session_stdin, temp_root, capsys
):
    """config.toml 이 invalid → lib.config 가 default Config fallback (graceful).
    on_recap 은 default 값 (ttl=60, language='en') 으로 메시지 출력."""
    (temp_root / "config.toml").write_text("not valid = = =", encoding="utf-8")
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    raw = capsys.readouterr().out
    parsed = json.loads(raw)
    assert "systemMessage" in parsed
    assert "Cache dies at" in parsed["systemMessage"]  # default lang = "en"


def test_systemmessage_is_valid_json(session_stdin, temp_root, capsys):
    """stdout 이 valid JSON + systemMessage key 존재 + emoji raw 출력."""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\ncache_ttl_minutes = 50\nlanguage = "ko"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    raw = capsys.readouterr().out
    assert "🪦" in raw  # ensure_ascii=False 확인 (raw emoji)
    parsed = json.loads(raw)
    assert "systemMessage" in parsed


# ---- set 예산 잔량 2줄째 (spec §8) ----

class TestSetBudgetSecondLine:
    """set_budget_remaining > 0 이면 recap 2줄째에 최대 생존 시한 표시."""

    def _charge(self, cn_root, sid: str, remaining: int, total: int) -> None:
        """marker 파일에 set 예산 기록 (테스트 픽스처 헬퍼)."""
        from lib.marker import Marker
        from lib.session_id import sanitize
        m = Marker.load(sanitize(sid))
        m.set_budget_remaining = remaining
        m.set_budget_total = total
        m.save()

    def _run(self, monkeypatch, cn_root, sid: str) -> None:
        """stdin 에 session_id 주입 후 main() 실행."""
        import io
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
        # config.toml 이 없으면 auto-create (defaults: interval=50, ttl=60, language=en)
        from scripts.on_recap import main
        main()

    @freeze_time("2026-06-10 19:00:00")
    def test_two_lines_when_budget_remaining(self, cn_root, monkeypatch, capsys):
        """set_budget_remaining=2, interval=50, ttl=60 → 생존 시한 21:40 (2줄)."""
        sid = "recap-sid"
        self._charge(cn_root, sid, remaining=2, total=2)
        # config: interval=50, ttl=60, language=en (default)
        (cn_root / "config.toml").write_text(
            '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\n'
            'cache_ttl_minutes = 60\nlanguage = "en"\n',
            encoding="utf-8",
        )
        self._run(monkeypatch, cn_root, sid)
        out = json.loads(capsys.readouterr().out)
        lines = out["systemMessage"].split("\n")
        # 2줄 구성 검증
        assert len(lines) == 2
        assert lines[0].startswith("🪦")
        # 생존 시한 = 19:00 + 2×50m + 60m = 21:40
        assert lines[1].startswith("🔥")
        assert "21:40" in lines[1]

    @freeze_time("2026-06-10 19:00:00")
    def test_one_line_when_no_budget(self, cn_root, monkeypatch, capsys):
        """set_budget_remaining=0 → 기존 1줄만 출력."""
        sid = "recap-sid2"
        # marker 에 예산 없음 (0이 기본값이므로 파일 생성 불필요)
        (cn_root / "config.toml").write_text(
            '[general]\nmode = "auto"\ncache_ttl_minutes = 60\nlanguage = "en"\n',
            encoding="utf-8",
        )
        self._run(monkeypatch, cn_root, sid)
        out = json.loads(capsys.readouterr().out)
        assert "\n" not in out["systemMessage"]


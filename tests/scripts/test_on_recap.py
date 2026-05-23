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



@freeze_time("2026-05-23 01:00:00")
def test_auto_mode_normal_message(session_stdin, temp_root, capsys):
    """auto mode + interval=50, fire=10:00 (UTC 01:00) → '🪦 캐시는 10:50 KST 에 살리러 갈게요!'"""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["systemMessage"] == "🪦 캐시는 10:50 KST 에 살리러 갈게요!"


@freeze_time("2026-05-23 14:55:00")
def test_midnight_rollover(session_stdin, temp_root, capsys):
    """fire=23:55 (UTC 14:55), interval=30 → '00:25 KST'"""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 30\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "00:25 KST" in out["systemMessage"]

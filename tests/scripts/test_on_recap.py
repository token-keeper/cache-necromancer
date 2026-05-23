"""Tests for scripts/on_recap.py + hooks/hooks.json 구조 (recap design spec)."""
import json
import sys
from pathlib import Path

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

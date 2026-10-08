"""Tests for scripts/on_recap.py (Stop: latest_fire 기록만) + hooks/hooks.json 구조."""
import io
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_hooks_json() -> dict:
    path = _PROJECT_ROOT / "hooks" / "hooks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_hooks_json_stop_array_has_recap_only():
    """Stop 배열엔 sync on_recap 하나 (v0.10.0: refresh 는 mod 가 --now 로 실행)."""
    data = _load_hooks_json()
    stop = data["hooks"]["Stop"]
    assert len(stop) == 1, f"Stop 배열 객체 1개 기대, 실제 {len(stop)}"


def test_hooks_json_first_stop_is_sync_recap():
    """첫번째 = on_recap.py (sync, asyncRewake X, timeout 5)."""
    data = _load_hooks_json()
    first = data["hooks"]["Stop"][0]["hooks"][0]
    assert "on_recap.py" in first["command"]
    assert first.get("asyncRewake") is not True
    assert first["timeout"] == 5


def test_hooks_json_has_no_refresh_hook():
    """v0.10.0: refresh.py 를 거는 command hook 이 없다 (asyncRewake 대기 프로세스 제거)."""
    text = (_PROJECT_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
    assert "refresh.py" not in text
    assert "asyncRewake" not in text


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


def test_stop_records_latest_fire(session_stdin, temp_root):
    """v0.10.0: Stop(on_recap) 1회 → marker.latest_fire = Stop 시각 (cn_status·cn_set 기준)."""
    import time
    from lib.session_id import sanitize
    from scripts.on_recap import main
    before = time.time_ns()
    assert main() == 0
    from lib.marker import Marker
    m = Marker.load(sanitize(session_stdin))
    assert before <= m.latest_fire <= time.time_ns()


@pytest.mark.parametrize(
    "toml",
    [
        '[general]\nlanguage = "ko"\n',
        '[general]\nmax_refresh_count = 5\n[wake]\narm = "always"\n[display]\nrecap_style = "box"\n',
    ],
)
def test_stop_prints_nothing(session_stdin, temp_root, capsys, toml):
    """v0.11.0: recap 박스 없음 — always·예산 있음·recap_style=box 여도 stdout 비고 latest_fire 만 기록."""
    from lib.marker import Marker
    from lib.session_id import sanitize
    (temp_root / "config.toml").write_text(toml, encoding="utf-8")
    m = Marker.load(sanitize(session_stdin))
    m.set_budget_remaining = 2
    m.set_budget_total = 3
    m.wake_count = 1
    m.save()
    from scripts.on_recap import main
    assert main() == 0
    assert capsys.readouterr().out == ""
    after = Marker.load(sanitize(session_stdin))
    assert after.latest_fire > 0
    # 예산·횟수는 건드리지 않는다
    assert (after.set_budget_remaining, after.set_budget_total, after.wake_count) == (2, 3, 1)


def test_stop_creates_config_when_missing(session_stdin, temp_root, capsys):
    """첫 Stop 에 config.toml 이 없으면 기본 템플릿을 만든다 (출력은 여전히 없음)."""
    path = temp_root / "config.toml"
    assert not path.exists()
    from scripts.on_recap import main
    assert main() == 0
    assert path.exists()
    assert "[general]" in path.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""

"""CLAUDE_PLUGIN_OPTION_MODE 는 v0.5.0 부터 무시된다 (codex 리뷰 F3)."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import ensure_config_file, load_config  # noqa: E402


def test_env_mode_is_ignored_on_create(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "hybrid")
    p = tmp_path / "config.toml"
    ensure_config_file(p)
    text = p.read_text()
    assert "mode" not in text          # legacy 키를 시드하지 않음
    assert 'arm = "manual"' in text    # 신규 설치 기본 = manual
    cfg = load_config(p)
    assert cfg.wake.arm == "manual"

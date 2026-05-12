"""Tests for scripts/cn_config.py"""
import pytest


@pytest.fixture
def config_module(cn_root, monkeypatch):
    import importlib
    import scripts.cn_config as mod
    importlib.reload(mod)
    monkeypatch.setattr(mod, "_resolve_root", lambda: cn_root)
    return mod


def test_config_no_file_shows_defaults(config_module, capsys):
    """config.toml 없을 때 기본값 + 안내 표시."""
    assert config_module.main() == 0
    out = capsys.readouterr().out
    assert "config 파일" in out
    assert "기본값 사용 중" in out
    assert "hybrid" in out  # 기본 mode
    assert "3가지 모드" in out
    assert "🔔 notify" in out
    assert "⚡ auto" in out
    assert "💀 hybrid" in out
    assert "설정 변경" in out


def test_config_file_shows_current_mode(config_module, capsys, cn_root):
    (cn_root / "config.toml").write_text(
        '[general]\nmode = "notify"\n'
    )
    # config 모듈 다시 로드
    import importlib
    import scripts.cn_config as mod
    importlib.reload(mod)
    import lib.config
    importlib.reload(lib.config)
    mod._resolve_root = lambda: cn_root
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "🔔 notify" in out


def test_config_shows_all_values(config_module, capsys):
    assert config_module.main() == 0
    out = capsys.readouterr().out
    # 핵심 설정 모두 노출
    assert "refresh_interval" in out
    assert "max_refresh_count" in out
    assert "hybrid_wait" in out
    assert "fire_timeout" in out
    assert "terminal_bell" in out
    assert "imminent_threshold" in out

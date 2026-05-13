import pytest
from pathlib import Path
from lib.config import load_config


def test_env_var_overrides_default(monkeypatch, tmp_path):
    """CLAUDE_PLUGIN_OPTION_MODE 환경변수가 코드 기본값(hybrid)을 override."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    c = load_config(tmp_path / "missing.toml")
    assert c.mode == "notify"


def test_env_var_overrides_file_value(monkeypatch, tmp_path):
    """환경변수가 config.toml 의 mode 도 override."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    c = load_config(p)
    assert c.mode == "notify"


def test_file_value_used_when_env_var_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MODE", raising=False)
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    c = load_config(p)
    assert c.mode == "auto"


def test_invalid_env_var_raises(monkeypatch, tmp_path):
    """환경변수 값이 valid mode가 아니면 ValueError."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "garbage")
    with pytest.raises(ValueError, match="mode"):
        load_config(tmp_path / "missing.toml")


def test_empty_env_var_ignored(monkeypatch, tmp_path):
    """빈 문자열 환경변수는 무시 (override 없음 = 파일/기본값 사용)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "")
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    c = load_config(p)
    assert c.mode == "auto"

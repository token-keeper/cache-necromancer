"""Verify CLAUDE_PLUGIN_OPTION_MODE does NOT override config.toml at runtime.

PLAN decision D3 (revised): env var is only consulted at first-time template
creation by ``ensure_config_file``. ``load_config`` reads file + default only.
"""
from lib.config import load_config


def test_env_var_does_not_override_default(monkeypatch, tmp_path):
    """Env var set, file missing → default hybrid (env ignored at runtime)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    c = load_config(tmp_path / "missing.toml")
    assert c.mode == "hybrid"


def test_env_var_does_not_override_file(monkeypatch, tmp_path):
    """Env var set, file has different mode → file wins."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    c = load_config(p)
    assert c.mode == "auto"


def test_invalid_env_var_does_not_raise(monkeypatch, tmp_path):
    """Garbage env value does not cause load_config to raise (env is ignored)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "garbage")
    c = load_config(tmp_path / "missing.toml")
    assert c.mode == "hybrid"

import stat
import pytest
from pathlib import Path
from lib.config import ensure_config_file


def test_creates_default_when_missing(tmp_path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    assert path.exists()
    content = path.read_text()
    assert "[general]" in content
    assert "mode" in content
    assert "refresh_interval_minutes" in content


def test_does_not_overwrite_existing(tmp_path):
    """이미 있으면 절대 덮어쓰지 않음 (사용자 편집 보존)."""
    path = tmp_path / "config.toml"
    path.write_text("# my custom config\nmode = \"auto\"\n")
    ensure_config_file(path)
    assert path.read_text() == "# my custom config\nmode = \"auto\"\n"


def test_uses_env_mode_in_default_template(tmp_path, monkeypatch):
    """첫 생성 시 환경변수 mode 값을 템플릿에 반영."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    content = path.read_text()
    assert 'mode = "notify"' in content


def test_default_template_when_env_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MODE", raising=False)
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    assert 'mode = "hybrid"' in path.read_text()


def test_invalid_env_mode_falls_back_to_default(tmp_path, monkeypatch):
    """잘못된 환경변수 값은 템플릿 작성 시 무시 (load_config 가 별도로 raise)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "garbage")
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    assert 'mode = "hybrid"' in path.read_text()


def test_created_file_has_0600_permission(tmp_path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

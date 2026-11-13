import stat

from lib.config import ensure_config_file


def test_creates_default_when_missing(tmp_path):
    """템플릿은 v0.12.0 키 5개만 — 옛 키(arm·notify·grace·max_refresh_count) 없음."""
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    content = path.read_text()
    assert "[general]" in content
    assert "auto_wakes = 2" in content
    assert "refresh_interval_minutes = 50" in content
    assert "cache_ttl_minutes = 60" in content
    assert 'language = "en"' in content
    assert "[display]" in content
    assert "countdown = true" in content
    for old in ("[wake]", "[notify]", "[advanced]", "arm =", "grace_seconds",
                "max_refresh_count", "enabled =", "mode ="):
        assert old not in content


def test_template_loads_to_defaults(tmp_path):
    from lib.config import Config, load_config
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    assert load_config(path) == Config()


def test_does_not_overwrite_existing(tmp_path):
    """이미 있으면 절대 덮어쓰지 않음 (사용자 편집 보존)."""
    path = tmp_path / "config.toml"
    path.write_text("# my custom config\nmode = \"auto\"\n")
    ensure_config_file(path)
    assert path.read_text() == "# my custom config\nmode = \"auto\"\n"


def test_created_file_has_0600_permission(tmp_path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

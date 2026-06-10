import stat

from lib.config import ensure_config_file


def test_creates_default_when_missing(tmp_path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    assert path.exists()
    content = path.read_text()
    assert "[general]" in content
    assert "mode" not in content          # v0.5.0: legacy 키 미시드
    assert 'arm = "manual"' in content    # 신규 설치 기본
    assert "enabled = true" in content    # notify 기본 on
    assert "grace_seconds = 60" in content
    assert "refresh_interval_minutes = 50" in content
    assert "cache_ttl_minutes = 60" in content
    assert "max_refresh_count = 10" in content
    assert 'language = "en"' in content
    assert "[notify]" in content
    assert "[wake]" in content
    # v0.3.0: [advanced] 섹션 없음
    assert "[advanced]" not in content


def test_does_not_overwrite_existing(tmp_path):
    """이미 있으면 절대 덮어쓰지 않음 (사용자 편집 보존)."""
    path = tmp_path / "config.toml"
    path.write_text("# my custom config\nmode = \"auto\"\n")
    ensure_config_file(path)
    assert path.read_text() == "# my custom config\nmode = \"auto\"\n"


def test_env_mode_is_ignored_on_create(tmp_path, monkeypatch):
    """v0.5.0: CLAUDE_PLUGIN_OPTION_MODE 는 무시 — 신규 설치 항상 manual."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODE", "notify")
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    content = path.read_text()
    assert "mode" not in content          # legacy 키를 시드하지 않음
    assert 'arm = "manual"' in content    # 신규 설치 기본 = manual


def test_created_file_has_0600_permission(tmp_path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

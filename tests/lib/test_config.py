"""Tests for lib.config (v0.3.0 — 옵션 5개 + deprecated detect)."""
import pytest

from lib.config import Config, load_config


def test_load_defaults_when_file_missing(tmp_path):
    """존재하지 않는 path → 기본값 Config."""
    c = load_config(tmp_path / "nonexistent.toml")
    assert c.mode == "hybrid"
    assert c.refresh_interval_minutes == 50  # v0.2.x 55 → 50
    assert c.cache_ttl_minutes == 60  # Anthropic 1h ext cache 기본
    assert c.max_refresh_count == 10
    assert c.refresh.hybrid_wait_seconds == 60
    assert c.notify.system_notification is True


def test_load_partial_overrides_keeps_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[general]\nmode = "auto"\nmax_refresh_count = 20\n'
    )
    c = load_config(p)
    assert c.mode == "auto"
    assert c.max_refresh_count == 20
    assert c.refresh_interval_minutes == 50  # default
    assert c.refresh.hybrid_wait_seconds == 60  # default


def test_load_full_v030_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[general]
mode = "notify"
refresh_interval_minutes = 30
max_refresh_count = 5

[notify]
system_notification = false

[refresh]
hybrid_wait_seconds = 90
"""
    )
    c = load_config(p)
    assert c.mode == "notify"
    assert c.refresh_interval_minutes == 30
    assert c.max_refresh_count == 5
    assert c.notify.system_notification is False
    assert c.refresh.hybrid_wait_seconds == 90


def test_invalid_mode_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "invalid"\n')
    with pytest.raises(ValueError, match="mode"):
        load_config(p)


def test_empty_file_uses_defaults(tmp_path):
    p = tmp_path / "empty.toml"
    p.write_text("")
    c = load_config(p)
    assert c == Config()


def test_syntax_error_falls_back_to_defaults(tmp_path, capsys):
    """TOML syntax error → 기본값 + stderr 경고."""
    p = tmp_path / "broken.toml"
    p.write_text("[general\nmode = bad")  # 닫는 ] 없음
    c = load_config(p)
    assert c == Config()
    err = capsys.readouterr().err
    assert "syntax error" in err


def test_deprecated_options_detected_and_ignored(tmp_path, capsys):
    """v0.2.x 폐기 옵션 → stderr 경고 + load 성공 (옵션 무시)."""
    p = tmp_path / "c.toml"
    p.write_text(
        """
[general]
mode = "auto"

[refresh]
hybrid_wait_seconds = 70
prompt = "ping"
fire_timeout_seconds = 120

[notify]
system_notification = false
terminal_bell = true
imminent_threshold_minutes = 5

[advanced]
daemon_poll_max_seconds = 30
"""
    )
    c = load_config(p)
    # 호환 옵션은 정상 로드
    assert c.mode == "auto"
    assert c.refresh.hybrid_wait_seconds == 70
    assert c.notify.system_notification is False
    # 폐기 옵션 무시 — RefreshConfig/NotifyConfig 가 받지 않음
    assert not hasattr(c.refresh, "prompt")
    assert not hasattr(c.notify, "terminal_bell")
    # stderr 경고
    err = capsys.readouterr().err
    assert "deprecated" in err
    assert "refresh.prompt" in err
    assert "refresh.fire_timeout_seconds" in err
    assert "notify.terminal_bell" in err
    assert "notify.imminent_threshold_minutes" in err
    assert "[advanced]" in err


def test_no_warning_when_no_deprecated_options(tmp_path, capsys):
    p = tmp_path / "clean.toml"
    p.write_text(
        '[general]\nmode = "auto"\n[refresh]\nhybrid_wait_seconds = 30\n'
    )
    load_config(p)
    err = capsys.readouterr().err
    assert "deprecated" not in err


def test_config_language_default_is_en(tmp_path):
    """config 에 language 미지정 시 default = 'en'."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    c = load_config(p)
    assert c.language == "en"


def test_config_language_loaded_from_toml(tmp_path):
    """[general].language 값이 Config 에 반영."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\nlanguage = "ko"\n')
    c = load_config(p)
    assert c.language == "ko"


def test_config_language_unknown_value_loaded_as_is(tmp_path):
    """load 단계는 validate X (normalize_language 단계에서 fallback)."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\nlanguage = "xx"\n')
    c = load_config(p)
    assert c.language == "xx"


def test_config_cache_ttl_default_60(tmp_path):
    """config 에 cache_ttl_minutes 미지정 시 default = 60 (1h ext cache)."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\n')
    c = load_config(p)
    assert c.cache_ttl_minutes == 60


def test_config_cache_ttl_loaded_from_toml(tmp_path):
    """[general].cache_ttl_minutes 값이 Config 에 반영 (5min cache 케이스)."""
    p = tmp_path / "c.toml"
    p.write_text('[general]\nmode = "auto"\ncache_ttl_minutes = 5\n')
    c = load_config(p)
    assert c.cache_ttl_minutes == 5

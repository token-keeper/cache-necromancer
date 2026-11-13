"""Tests for lib.config (v0.12.0 — 키 5개, 옛 키 무시, 값 검증)."""
import pytest

from lib.config import (
    OBSOLETE_KEYS,
    SET_CAP,
    Config,
    detect_obsolete_keys,
    load_config,
    parse_config_file,
)


def _load(tmp_path, body: str) -> Config:
    p = tmp_path / "c.toml"
    p.write_text(body, encoding="utf-8")
    return load_config(p)


def test_defaults_when_file_missing(tmp_path):
    c = load_config(tmp_path / "nonexistent.toml")
    assert c == Config()
    assert c.auto_wakes == 2
    assert c.refresh_interval_minutes == 50
    assert c.cache_ttl_minutes == 60
    assert c.language == "en"
    assert c.display.countdown is True


def test_set_cap_is_10():
    assert SET_CAP == 10


def test_empty_file_uses_defaults(tmp_path):
    assert _load(tmp_path, "") == Config()


def test_syntax_error_falls_back_to_defaults(tmp_path, capsys):
    c = _load(tmp_path, "[general\nauto_wakes = 5")
    assert c == Config()
    assert "syntax error" in capsys.readouterr().err


def test_all_keys_loaded(tmp_path):
    c = _load(
        tmp_path,
        '[general]\nauto_wakes = 3\nrefresh_interval_minutes = 45\n'
        'cache_ttl_minutes = 5\nlanguage = "ko"\n[display]\ncountdown = false\n',
    )
    assert (c.auto_wakes, c.refresh_interval_minutes, c.cache_ttl_minutes) == (3, 45, 5)
    assert c.language == "ko"
    assert c.display.countdown is False


def test_auto_wakes_0_allowed(tmp_path):
    assert _load(tmp_path, "[general]\nauto_wakes = 0\n").auto_wakes == 0


class TestObsoleteKeysIgnored:
    def test_old_keys_ignored_default_auto_wakes_2(self, tmp_path, capsys):
        """옛 max_refresh_count = 10 · always 는 auto_wakes 로 이어지지 않는다 — 기본 2."""
        c = _load(
            tmp_path,
            '[general]\nmode = "hybrid"\nmax_refresh_count = 10\n'
            '[wake]\narm = "always"\ngrace_seconds = 60\n'
            '[notify]\nenabled = true\nsystem_notification = false\n'
            '[refresh]\nhybrid_wait_seconds = 90\n'
            '[advanced]\nx = 1\n[display]\nrecap_style = "box"\n',
        )
        assert c == Config()
        assert capsys.readouterr().err == ""   # 경고 없이 로드

    def test_detect_obsolete_keys_key_level(self):
        data = {
            "general": {"mode": "hybrid", "max_refresh_count": 5, "auto_wakes": 2},
            "wake": {"arm": "always", "grace_seconds": 60},
            "notify": {"enabled": True},
            "refresh": {"prompt": "x"},
            "advanced": {"daemon_poll_max_seconds": 30},
            "display": {"recap_style": "box", "countdown": True},
        }
        found = detect_obsolete_keys(data)
        assert sorted(found) == sorted([
            "general.mode", "general.max_refresh_count", "wake.arm", "wake.grace_seconds",
            "notify.enabled", "refresh.prompt", "advanced.daemon_poll_max_seconds",
            "display.recap_style",
        ])

    def test_detect_obsolete_keys_clean(self):
        assert detect_obsolete_keys({}) == []
        assert detect_obsolete_keys({"general": {"auto_wakes": 2}}) == []

    def test_obsolete_keys_format(self):
        assert "general.mode" in OBSOLETE_KEYS
        assert "wake.*" in OBSOLETE_KEYS
        assert "display.recap_style" in OBSOLETE_KEYS


class TestInvalidValues:
    @pytest.mark.parametrize("body,key", [
        ('auto_wakes = 11', "general.auto_wakes"),
        ('auto_wakes = -1', "general.auto_wakes"),
        ('auto_wakes = "3"', "general.auto_wakes"),
        ('auto_wakes = 2.5', "general.auto_wakes"),
        ('auto_wakes = true', "general.auto_wakes"),
        ('refresh_interval_minutes = 0', "general.refresh_interval_minutes"),
        ('refresh_interval_minutes = "30"', "general.refresh_interval_minutes"),
        ('cache_ttl_minutes = 0', "general.cache_ttl_minutes"),
        ('language = "xx"', "general.language"),
    ])
    def test_invalid_key_falls_back_with_warning(self, tmp_path, capsys, body, key):
        c = _load(tmp_path, f"[general]\n{body}\n")
        assert c == Config()
        err = capsys.readouterr().err
        assert f"[cn:warn] invalid {key}:" in err
        assert "기본값" in err

    def test_only_bad_key_is_reset(self, tmp_path, capsys):
        c = _load(tmp_path, '[general]\nauto_wakes = 99\nrefresh_interval_minutes = 45\n')
        assert c.auto_wakes == 2
        assert c.refresh_interval_minutes == 45

    def test_countdown_non_bool(self, tmp_path, capsys):
        c = _load(tmp_path, '[display]\ncountdown = "no"\n')
        assert c.display.countdown is True
        assert "display.countdown" in capsys.readouterr().err

    def test_non_table_section_ignored(self, tmp_path):
        assert _load(tmp_path, 'general = 5\n') == Config()


def test_parse_config_file_missing_and_error(tmp_path):
    assert parse_config_file(tmp_path / "none.toml") == ({}, None)
    p = tmp_path / "bad.toml"
    p.write_text("[x\n")
    data, err = parse_config_file(p)
    assert data == {} and err


def test_non_utf8_config_falls_back(tmp_path, capsys):
    """비 UTF-8 바이트 → 예외 없이 기본값 + 경고 (refresh·cn_set 이 traceback 으로 죽지 않게)."""
    p = tmp_path / "c.toml"
    p.write_bytes(b'[general]\nlanguage = "\xff\xfe"\n')
    data, err = parse_config_file(p)
    assert data == {} and err
    assert load_config(p) == Config()
    assert "syntax error" in capsys.readouterr().err

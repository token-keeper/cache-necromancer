"""Tests for lib.config"""
import pytest

from lib.config import Config, load_config


def test_load_defaults_when_file_missing(tmp_path):
    """존재하지 않는 path → 기본값 Config."""
    c = load_config(tmp_path / "nonexistent.toml")
    assert c.mode == "hybrid"
    assert c.refresh_interval_minutes == 55
    assert c.max_refresh_count == 10
    assert c.refresh.prompt == "."
    assert c.refresh.hybrid_wait_seconds == 60
    # v0.2.2: 120 → 240 (opus + 큰 transcript cache_creation 마진).
    assert c.refresh.fire_timeout_seconds == 240
    assert c.notify.terminal_bell is True
    assert c.notify.system_notification is True
    assert c.notify.imminent_threshold_minutes == 5
    assert c.advanced.daemon_poll_max_seconds == 60
    assert c.advanced.session_ttl_hours == 24
    assert c.advanced.daemon_idle_shutdown_minutes == 60
    assert c.advanced.clock_drift_threshold_seconds == 30
    assert c.advanced.clock_drift_postpone_minutes == 5
    assert c.advanced.fire_stop_watchdog_seconds == 120
    assert c.advanced.consecutive_fire_failures_disable == 5
    assert c.advanced.cache_cold_max_retries == 2
    assert c.advanced.backoff_base_seconds == 30.0
    assert c.advanced.backoff_cap_seconds == 1800.0
    assert c.advanced.interactive_input_quiet_seconds == 30
    assert c.advanced.state_lock_deadline_seconds == 4.0


def test_load_partial_overrides_keeps_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[general]\nmode = "auto"\nmax_refresh_count = 20\n'
    )
    c = load_config(p)
    assert c.mode == "auto"
    assert c.max_refresh_count == 20
    # 안 적은 키는 기본값
    assert c.refresh_interval_minutes == 55
    assert c.refresh.prompt == "."


def test_load_full_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[general]
mode = "notify"
refresh_interval_minutes = 30
max_refresh_count = 5

[refresh]
prompt = "ping"
hybrid_wait_seconds = 90
fire_timeout_seconds = 60

[notify]
terminal_bell = false
system_notification = false
imminent_threshold_minutes = 10

[advanced]
daemon_poll_max_seconds = 30
cache_cold_max_retries = 3
"""
    )
    c = load_config(p)
    assert c.mode == "notify"
    assert c.refresh_interval_minutes == 30
    assert c.max_refresh_count == 5
    assert c.refresh.prompt == "ping"
    assert c.refresh.hybrid_wait_seconds == 90
    assert c.refresh.fire_timeout_seconds == 60
    assert c.notify.terminal_bell is False
    assert c.notify.system_notification is False
    assert c.notify.imminent_threshold_minutes == 10
    assert c.advanced.daemon_poll_max_seconds == 30
    assert c.advanced.cache_cold_max_retries == 3


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

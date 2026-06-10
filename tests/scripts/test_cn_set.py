"""Tests for scripts/cn_set.py (spec §4)."""
import sys
from pathlib import Path

import pytest
from freezegun import freeze_time

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.cn_set import main  # noqa: E402

SID = "set-test-sid"


@pytest.fixture
def sid_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    return sanitize(SID)


def _write_config(cn_root, *, arm="manual", max_refresh=10, interval=50, ttl=60):
    (cn_root / "config.toml").write_text(
        "[general]\n"
        f"refresh_interval_minutes = {interval}\n"
        f"cache_ttl_minutes = {ttl}\n"
        f"max_refresh_count = {max_refresh}\n"
        f'[wake]\narm = "{arm}"\n',
        encoding="utf-8",
    )


class TestCharge:
    @freeze_time("2026-06-10 19:00:00")
    def test_charge_2(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = 1
        m.save()
        rc = main(["2"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2" in out and "21:40" in out      # 19:00 + 2×50m + 60m
        m2 = Marker.load(sid_env)
        assert m2.set_budget_remaining == 2
        assert m2.set_budget_total == 2
        assert m2.set_charged_at_ns > 0

    def test_charge_capped_at_max(self, cn_root, sid_env, capsys):
        _write_config(cn_root, max_refresh=10)
        rc = main(["15"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "10" in out and "15" in out
        assert Marker.load(sid_env).set_budget_remaining == 10

    def test_first_turn_note_when_no_fire(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["1"])
        assert "⚠️" in capsys.readouterr().out    # latest_fire == 0

    def test_zero_cancels(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["3"])
        capsys.readouterr()
        rc = main(["0"])
        assert rc == 0
        m = Marker.load(sid_env)
        assert m.set_budget_remaining == 0
        assert m.set_budget_total == 0

    def test_always_is_noop(self, cn_root, sid_env, capsys):
        _write_config(cn_root, arm="always")
        rc = main(["2"])
        assert rc == 0
        assert "/cn:config" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_remaining == 0

    def test_no_arg_shows_status(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["2"])
        capsys.readouterr()
        rc = main([])
        assert rc == 0
        assert "2" in capsys.readouterr().out

    def test_no_arg_no_budget_shows_none(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        rc = main([])
        assert rc == 0
        assert "/cn:set" in capsys.readouterr().out   # status_none 안내

    @pytest.mark.parametrize("bad", ["abc", "-1", "1.5"])
    def test_invalid_arg_shows_usage(self, cn_root, sid_env, capsys, bad):
        _write_config(cn_root)
        rc = main([bad])
        assert rc == 0
        assert "/cn:set" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_remaining == 0

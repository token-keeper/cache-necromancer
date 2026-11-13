"""Tests for scripts/cn_set.py (v0.12.0 — 덮어쓰기·끄기·조회)."""
import sys
import time
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
MIN_NS = 60 * 1_000_000_000


@pytest.fixture
def sid_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    return sanitize(SID)


def _write_config(cn_root, *, auto_wakes=2, interval=50, ttl=60, lang="ko"):
    (cn_root / "config.toml").write_text(
        "[general]\n"
        f"auto_wakes = {auto_wakes}\n"
        f"refresh_interval_minutes = {interval}\n"
        f"cache_ttl_minutes = {ttl}\n"
        f'language = "{lang}"\n',
        encoding="utf-8",
    )


class TestCharge:
    @freeze_time("2026-06-10 19:00:00")
    def test_charge_2_survive_from_latest_fire(self, cn_root, sid_env, capsys):
        """생존 시각 = latest_fire + 2×50 + 60분 (§3 식, now 아님)."""
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 10 * MIN_NS     # 18:50
        m.save()
        assert main(["2"]) == 0
        out = capsys.readouterr().out
        assert "깨우기 2회 충전" in out and "21:30" in out
        assert "이 세션에만 적용" in out
        m2 = Marker.load(sid_env)
        assert (m2.set_budget_remaining, m2.set_budget_total) == (2, 2)
        assert m2.set_charged_at_ns > 0

    @freeze_time("2026-06-10 19:00:00")
    def test_charge_without_fire_uses_now(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["1"])
        assert "20:50" in capsys.readouterr().out       # 19:00 + 50 + 60

    def test_charge_capped_at_10(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        assert main(["15"]) == 0
        out = capsys.readouterr().out
        assert "최대 10회까지만 충전돼요" in out
        assert Marker.load(sid_env).set_budget_remaining == 10

    def test_charge_10_no_cap_note(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["10"])
        assert "최대 10회" not in capsys.readouterr().out

    def test_charge_clears_wake_off(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["off"])
        main(["3"])
        m = Marker.load(sid_env)
        assert m.wake_off is False
        assert m.set_budget_remaining == 3


class TestExpired:
    def test_charge_after_cache_expired_says_so(self, cn_root, sid_env, capsys):
        """latest_fire + ttl 이 지났으면 생존 시각 대신 만료 안내 (mod 는 만료된 base 로 안 깨움)."""
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 90 * MIN_NS
        m.save()
        main(["3"])
        out = capsys.readouterr().out
        assert "깨우기 3회 충전 — 지금 캐시는 이미 만료 — 다음 자리비움부터 적용" in out
        assert "캐시 최대" not in out

    def test_interval_ge_ttl_survive_is_ttl_only(self, cn_root, sid_env, capsys):
        with freeze_time("2026-06-10 19:00:00"):
            _write_config(cn_root, interval=60, ttl=60)
            main(["3"])
            assert "20:00" in capsys.readouterr().out     # 19:00 + 0×60 + 60


class TestOff:
    @pytest.mark.parametrize("arg", ["0", "off", "OFF", "Off"])
    def test_zero_and_off_turn_wake_off(self, cn_root, sid_env, capsys, arg):
        _write_config(cn_root)
        main(["3"])
        capsys.readouterr()
        assert main([arg]) == 0
        assert "이 세션 깨우기를 껐어요" in capsys.readouterr().out
        m = Marker.load(sid_env)
        assert m.wake_off is True
        assert (m.set_budget_remaining, m.set_budget_total, m.set_charged_at_ns) == (0, 0, 0)


class TestStatus:
    def test_status_off(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["off"])
        capsys.readouterr()
        main([])
        assert "깨우기 꺼짐 (이 세션)" in capsys.readouterr().out

    def test_status_override(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["3"])
        capsys.readouterr()
        main([])
        assert "이번 자리비움 깨우기 3회 남음" in capsys.readouterr().out

    def test_status_auto(self, cn_root, sid_env, capsys):
        _write_config(cn_root, auto_wakes=2)
        m = Marker.load(sid_env)
        m.wake_count = 1
        m.save()
        main([])
        assert "자동 깨우기 1회 남음" in capsys.readouterr().out

    def test_status_auto_disabled(self, cn_root, sid_env, capsys):
        _write_config(cn_root, auto_wakes=0)
        main([])
        assert "자동 깨우기 꺼짐 (설정 auto_wakes = 0)" in capsys.readouterr().out

    def test_status_english_default(self, cn_root, sid_env, capsys):
        """설정 파일 없음 → en, 기본 auto_wakes 2."""
        main([])
        assert "2 auto wake(s) left" in capsys.readouterr().out


class TestErrors:
    @pytest.mark.parametrize("bad", ["abc", "-1", "1.5", "²"])
    def test_invalid_arg_shows_usage(self, cn_root, sid_env, capsys, bad):
        _write_config(cn_root)
        assert main([bad]) == 0
        assert "사용법: /cn:set N" in capsys.readouterr().out
        m = Marker.load(sid_env)
        assert m.set_budget_remaining == 0
        assert m.wake_off is False

    def test_save_oserror_no_success_message(self, cn_root, sid_env, capsys, monkeypatch):
        """save 실패 — traceback 없이 경고만, 성공 메시지 출력 금지."""
        _write_config(cn_root)

        def bad_save(self):
            raise OSError("simulated")

        monkeypatch.setattr(Marker, "save", bad_save)
        assert main(["2"]) == 0
        out = capsys.readouterr().out
        assert "⚠️" in out
        assert "충전" not in out

    def test_no_session(self, cn_root, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert main(["2"]) == 0
        assert "session_id" in capsys.readouterr().out

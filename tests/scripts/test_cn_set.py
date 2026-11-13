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

    def test_interval_ge_ttl_hides_count(self, cn_root, sid_env, capsys):
        """v0.13.0 D: 깨울 수 없으면 띠처럼 횟수를 보이지 않는다 (충전 자체는 저장)."""
        _write_config(cn_root, interval=60, ttl=60)
        main(["3"])
        out = capsys.readouterr().out
        assert "깨울 수 없어요" in out and "3회" not in out
        assert Marker.load(sid_env).set_budget_total == 3
        main([])
        out = capsys.readouterr().out
        assert "깨울 수 없어요" in out and "남음" not in out


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
        for arg in ("2", "off", "auto", "2h"):          # 저장 실패는 exit 1 (패널이 빨간 줄로)
            assert main([arg]) == 1
            out = capsys.readouterr().out
            assert out.startswith("⚠️")
            assert "충전" not in out and "껐어요" not in out and "되돌렸어요" not in out

    def test_no_session(self, cn_root, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert main(["2"]) == 0
        assert "session_id" in capsys.readouterr().out


class TestAuto:
    def test_auto_clears_off_and_override(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.wake_off, m.set_budget_remaining, m.set_budget_total, m.set_charged_at_ns = True, 3, 3, 5
        m.save()
        assert main(["AUTO"]) == 0
        out = capsys.readouterr().out
        assert "자동 깨우기로 되돌렸어요" in out and "자동 깨우기 2회 남음" in out
        m2 = Marker.load(sid_env)
        assert (m2.wake_off, m2.set_budget_remaining, m2.set_budget_total,
                m2.set_charged_at_ns) == (False, 0, 0, 0)


class TestChargeUntil:
    """시간·시각 인자 — N = ceil((목표 − 기준 − ttl) / interval). 시각은 freeze_time 으로 고정."""

    @freeze_time("2026-06-10 19:00:00")
    @pytest.mark.parametrize("arg,n", [("2h", 2), ("90m", 1), ("1h30m", 1), ("4h", 4), ("61m", 1)])
    def test_duration_from_latest_fire(self, cn_root, sid_env, capsys, arg, n):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 10 * MIN_NS   # 18:50 → ttl 만으로 19:50
        m.save()
        assert main([arg]) == 0
        assert f"깨우기 {n}회 충전" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_total == n

    @freeze_time("2026-06-10 19:00:00")
    def test_duration_without_fire_uses_now(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["2h"])                                    # ceil((120 − 60) / 50) = 2
        assert "깨우기 2회 충전" in capsys.readouterr().out

    @freeze_time("2026-06-10 19:00:00")
    def test_expired_cache_anchor_is_now(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 90 * MIN_NS   # 만료 → 기준 = 지금
        m.save()
        main(["2h"])
        assert "깨우기 2회 충전" in capsys.readouterr().out

    @freeze_time("2026-06-10 19:00:00")
    def test_already_alive_no_charge(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 10 * MIN_NS
        m.save()
        main(["30m"])                                   # 19:30 ≤ 19:50
        out = capsys.readouterr().out
        assert "캐시가 이미 19:50까지 살아 있어요" in out
        assert Marker.load(sid_env).set_budget_total == 0

    @freeze_time("2026-06-10 19:00:00")
    def test_no_fire_short_target_no_alive_promise(self, cn_root, sid_env, capsys):
        """latest_fire 없음 → 기준 now 대체, N≤0 이어도 "이미 살아 있음"이라 하지 않는다."""
        _write_config(cn_root)
        main(["30m"])
        out = capsys.readouterr().out
        assert "살아 있는 캐시가 없어요" in out and "까지 살아 있어요" not in out
        assert Marker.load(sid_env).set_budget_total == 0

    @freeze_time("2026-06-10 19:00:00")
    def test_expired_short_target_no_alive_promise(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        m = Marker.load(sid_env)
        m.latest_fire = time.time_ns() - 90 * MIN_NS   # 만료
        m.save()
        main(["19:30"])                                 # 오늘 19:30, now+ttl 안 → N≤0
        out = capsys.readouterr().out
        assert "살아 있는 캐시가 없어요" in out and "까지 살아 있어요" not in out
        assert Marker.load(sid_env).set_budget_total == 0

    @freeze_time("2026-06-10 19:00:00")
    def test_capped_at_10(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["24h"])
        out = capsys.readouterr().out
        assert "깨우기 10회 충전" in out and "최대 10회까지만" in out and "캐시 최대" in out

    @freeze_time("2026-06-10 19:00:00")
    def test_clock_today_and_tomorrow(self, cn_root, sid_env, capsys):
        _write_config(cn_root)
        main(["21:00"])                                 # 오늘 21:00 → ceil(60/50) = 2
        assert "깨우기 2회 충전" in capsys.readouterr().out
        main(["18:00"])                                 # 지났으니 내일 18:00 → 23h → 상한 10
        assert "깨우기 10회 충전" in capsys.readouterr().out
        main(["19:00"])                                 # 지금과 같음 → 내일
        assert "깨우기 10회 충전" in capsys.readouterr().out

    @freeze_time("2026-06-10 23:30:00")
    def test_clock_past_midnight_not_capped(self, cn_root, sid_env, capsys):
        """자정 넘김 00:30 = 60분 뒤 → ceil((60 − 20) / 10) = 4. 하루가 더 밀리면 상한 10 이 된다."""
        _write_config(cn_root, interval=10, ttl=20)
        main(["00:30"])
        assert "깨우기 4회 충전" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_total == 4

    def test_interval_ge_ttl_no_charge(self, cn_root, sid_env, capsys):
        _write_config(cn_root, interval=60, ttl=60)
        main(["2h"])
        assert "깨울 수 없어요" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_total == 0

    @pytest.mark.parametrize("bad", ["0m", "0h0m", "h", "24:00", "9:60", "1h30", "2x", "1:5"])
    def test_bad_time_shows_usage(self, cn_root, sid_env, capsys, bad):
        _write_config(cn_root)
        main([bad])
        assert "사용법: /cn:set N" in capsys.readouterr().out
        assert Marker.load(sid_env).set_budget_total == 0

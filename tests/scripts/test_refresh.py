"""Tests for scripts/refresh.py (v0.12.0 — 깨우기 판정 하나로 통합).

mod 가 base + interval 에 `--now` 로 실행한다. latest_fire(마지막 Stop)는 on_recap.py 가
쓰므로 각 테스트가 marker 를 직접 심는다. 실제 sleep·알림 경로는 없다.
"""
import io
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker, marker_path  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.refresh import PING_PREFIX, _build_ping, main  # noqa: E402

SID = "test-now-sid"
MIN_NS = 60 * 1_000_000_000


def _write_config(cn_root, *, auto_wakes=None, extra=""):
    body = "[general]\n"
    if auto_wakes is not None:
        body += f"auto_wakes = {auto_wakes}\n"
    (cn_root / "config.toml").write_text(body + extra, encoding="utf-8")


def _seed(*, stop_ns=None, wake_count=0, budget=None, activity_ns=0,
          suppressed_ns=0, wake_off=False, turn_start_ns=0):
    """marker 심기. stop_ns 기본 = 51분 전 (정상 자리비움)."""
    m = Marker.load(sanitize(SID))
    m.latest_fire = time.time_ns() - 51 * MIN_NS if stop_ns is None else stop_ns
    m.wake_count = wake_count
    if budget is not None:
        m.set_budget_remaining, m.set_budget_total = budget
        m.set_charged_at_ns = m.latest_fire - 1
    m.last_user_activity_at_ns = activity_ns
    m.last_turn_start_at_ns = turn_start_ns
    m.suppressed_at_ns = suppressed_ns
    m.wake_off = wake_off
    m.save()
    return m


def _run(monkeypatch, argv=("--now",), sid=SID):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    return main(list(argv))


def _marker() -> Marker:
    return Marker.load(sanitize(SID))


def _log(cn_root) -> str:
    p = cn_root / f"cn.log.{date.today().isoformat()}"
    return p.read_text() if p.exists() else ""


class TestAutoWake:
    def test_default_auto_wakes_2_wakes(self, cn_root, monkeypatch, capsys):
        """설정 파일 없음 → 기본 auto_wakes 2 로 깨운다."""
        _seed()
        rc = _run(monkeypatch)
        assert rc == 2
        err = capsys.readouterr().err
        assert re.search(r"\[cn:keepalive \d{2}:\d{2}, 1/2\]", err)
        assert re.search(r"reply with exactly 'ok @\d{2}:\d{2} \(1/2\)'", err)
        m = _marker()
        assert m.wake_count == 1
        assert m.last_wake_at > 0
        assert m.last_wake_at_ns > 0
        assert m.last_wake_at == m.last_wake_at_ns // 1_000_000_000

    def test_second_wake_counts_2_of_2(self, cn_root, monkeypatch, capsys):
        _seed(wake_count=1)
        assert _run(monkeypatch) == 2
        assert "2/2" in capsys.readouterr().err
        assert _marker().wake_count == 2

    def test_auto_wakes_reached_skips_and_logs(self, cn_root, monkeypatch, capsys):
        _write_config(cn_root, auto_wakes=2)
        _seed(wake_count=2)
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert _marker().wake_count == 2
        assert "auto_wakes 2 도달" in _log(cn_root)

    def test_auto_wakes_0_never_wakes(self, cn_root, monkeypatch, capsys):
        _write_config(cn_root, auto_wakes=0)
        _seed()
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "auto_wakes 0 도달" in _log(cn_root)

    def test_old_keys_ignored_default_auto_wakes(self, cn_root, monkeypatch, capsys):
        """옛 always·max_refresh_count = 10 은 무시 → 기본 2 회만."""
        _write_config(cn_root, extra='max_refresh_count = 10\n[wake]\narm = "always"\n')
        _seed(wake_count=2)
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err

    def test_no_argv_same_path(self, cn_root, monkeypatch, capsys):
        """플래그 없이 불려도 같은 경로 — sleep 없이 판정."""
        _seed()
        monkeypatch.setattr("time.sleep", lambda s: pytest.fail("sleep 호출"))
        assert _run(monkeypatch, argv=()) == 2
        assert PING_PREFIX in capsys.readouterr().err

    def test_does_not_write_latest_fire(self, cn_root, monkeypatch):
        stop = time.time_ns() - 51 * MIN_NS
        _seed(stop_ns=stop)
        assert _run(monkeypatch) == 2
        assert _marker().latest_fire == stop

    def test_wake_log_line(self, cn_root, monkeypatch):
        _seed()
        _run(monkeypatch)
        assert f"[refresh] wake sid={sanitize(SID)} count=1 nm=1/2" in _log(cn_root)


class TestSetOverride:
    def test_override_consumes_budget_ping_is_consumed_over_total(
        self, cn_root, monkeypatch, capsys
    ):
        _seed(budget=(3, 3))
        assert _run(monkeypatch) == 2
        assert "1/3" in capsys.readouterr().err
        m = _marker()
        assert m.set_budget_remaining == 2
        assert m.wake_count == 1

    def test_override_has_no_auto_share(self, cn_root, monkeypatch, capsys):
        """덮어쓰기 중엔 자동 몫 없음 — 예산을 다 쓰면 auto_wakes 가 남아도 skip."""
        _write_config(cn_root, auto_wakes=5)
        _seed(budget=(0, 1), wake_count=1)
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "budget used" in _log(cn_root)

    def test_override_beyond_auto_wakes(self, cn_root, monkeypatch, capsys):
        """덮어쓰기는 auto_wakes 와 무관 — wake_count 가 auto_wakes 를 넘어도 깨운다."""
        _write_config(cn_root, auto_wakes=1)
        _seed(budget=(2, 3), wake_count=1)
        assert _run(monkeypatch) == 2
        assert "2/3" in capsys.readouterr().err

    def test_two_wake_full_chain(self, cn_root, monkeypatch, capsys):
        _seed(budget=(2, 2))
        assert _run(monkeypatch) == 2
        assert _run(monkeypatch) == 2
        assert _run(monkeypatch) == 0
        assert _marker().set_budget_remaining == 0


class TestWakeOff:
    def test_wake_off_skips_even_with_budget(self, cn_root, monkeypatch, capsys):
        _seed(wake_off=True, budget=(3, 3))
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "off, skip" in _log(cn_root)
        assert _marker().set_budget_remaining == 3


class TestSkipConditions:
    def test_no_stop_record_skips_without_zombie(self, cn_root, monkeypatch, capsys):
        """latest_fire == 0 (SessionEnd 가 marker 삭제) → skip, marker 재생성 없음."""
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert not marker_path(sanitize(SID)).exists()

    def test_prompt_after_stop_skips_midturn(self, cn_root, monkeypatch, capsys):
        """진행 중 turn(권한 대기·긴 도구): Stop 60분 전 → prompt 55분 전 → skip, 예산 유지."""
        now = time.time_ns()
        _seed(stop_ns=now - 60 * MIN_NS, activity_ns=now - 55 * MIN_NS, budget=(3, 3))
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert _marker().set_budget_remaining == 3

    def test_anchor_is_last_stop(self, cn_root, monkeypatch, capsys):
        stop = time.time_ns() - 2
        _seed(stop_ns=stop, activity_ns=stop + 1)
        assert _run(monkeypatch) == 0

    def test_idle_after_stop_wakes(self, cn_root, monkeypatch, capsys):
        now = time.time_ns()
        _seed(stop_ns=now - 50 * MIN_NS, activity_ns=now - 51 * MIN_NS)
        assert _run(monkeypatch) == 2


class TestTurnStartGate:
    """task-notification·팀메이트 메시지로 시작한 turn 도 진행 중이면 깨우지 않는다."""

    def _prompt(self, monkeypatch, prompt):
        from scripts import on_user_prompt
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
            {"session_id": SID, "prompt": prompt})))
        assert on_user_prompt.main() == 0

    @pytest.mark.parametrize("prompt", [
        '<teammate-message teammate_id="lead">보고</teammate-message>',
        "<task-notification>bg done</task-notification>",
    ])
    def test_non_user_turn_without_stop_skips(self, cn_root, monkeypatch, capsys, prompt):
        _seed(stop_ns=time.time_ns() - 51 * MIN_NS)
        self._prompt(monkeypatch, prompt)          # turn 시작, 아직 Stop 없음 (권한 대기 등)
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "Stop 뒤 turn 시작 있음" in _log(cn_root)

    @pytest.mark.parametrize("prompt", [
        '<teammate-message teammate_id="lead">보고</teammate-message>',
        "<task-notification>bg done</task-notification>",
    ])
    def test_non_user_turn_reaching_stop_wakes(self, cn_root, monkeypatch, capsys, prompt):
        _seed(stop_ns=time.time_ns() - 51 * MIN_NS, wake_count=1)
        self._prompt(monkeypatch, prompt)
        m = _marker()
        m.latest_fire = time.time_ns()             # 그 turn 의 Stop
        m.save()
        assert _run(monkeypatch) == 2
        assert "2/2" in capsys.readouterr().err    # 비활동이라 wake_count 리셋 없음

    def test_turn_start_field_gates_alone(self, cn_root, monkeypatch, capsys):
        stop = time.time_ns() - 51 * MIN_NS
        _seed(stop_ns=stop, turn_start_ns=stop + 1)
        assert _run(monkeypatch) == 0


class TestSuppress:
    def test_compact_while_idle_skips(self, cn_root, monkeypatch, capsys):
        """대기 중 수동 compact/clear: suppressed > max(activity, Stop) → skip."""
        now = time.time_ns()
        _seed(stop_ns=now - 51 * MIN_NS, activity_ns=now - 52 * MIN_NS,
              suppressed_ns=now - 40 * MIN_NS)
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "suppressed" in _log(cn_root)

    def test_auto_compact_mid_turn_then_stop_wakes(self, cn_root, monkeypatch, capsys):
        """입력(t0) → 같은 turn 에서 auto compact(t0+1분) → Stop(t0+5분): 새 캐시는 깨운다.

        옛 기준(suppressed > activity)이면 skip 됐다 (리뷰 MAJOR 3).
        """
        t0 = time.time_ns() - 60 * MIN_NS
        _seed(activity_ns=t0, suppressed_ns=t0 + MIN_NS, stop_ns=t0 + 5 * MIN_NS,
              budget=(3, 3))
        assert _run(monkeypatch) == 2
        assert PING_PREFIX in capsys.readouterr().err
        assert _marker().set_budget_remaining == 2

    def test_later_user_activity_releases_but_midturn_skips(self, cn_root, monkeypatch):
        """compact 뒤 진짜 입력 → 억제 해제지만 Stop 이전이라 진행 중 turn 으로 skip."""
        now = time.time_ns()
        _seed(stop_ns=now - 51 * MIN_NS, suppressed_ns=now - 50 * MIN_NS,
              activity_ns=now - 49 * MIN_NS)
        assert _run(monkeypatch) == 0


class TestFailClosed:
    def test_save_failure_no_ping_exit_0(self, cn_root, monkeypatch, capsys):
        """깨우기 저장 실패 → ping 없이 0 (상한이 캐시 유지보다 우선, 리뷰 MAJOR 2)."""
        _seed()

        def bad_save(self):
            raise OSError("simulated")

        monkeypatch.setattr(Marker, "save", bad_save)
        rc = _run(monkeypatch)
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "marker save 실패" in _log(cn_root)

    def test_readonly_marker_dir_never_pings(self, cn_root, monkeypatch, capsys):
        """쓸 수 없는 marker 디렉터리에서 여러 번 불려도 ping 0회."""
        _seed()
        d = marker_path(sanitize(SID)).parent
        d.chmod(0o555)
        try:
            rcs = [_run(monkeypatch) for _ in range(3)]
        finally:
            d.chmod(0o755)
        assert rcs == [0, 0, 0]
        assert PING_PREFIX not in capsys.readouterr().err


class TestEntry:
    def test_inactive_install_logs_and_skips(self, cn_root, monkeypatch, capsys):
        monkeypatch.setattr("scripts.refresh.is_latest_install", lambda: False)
        _seed()
        assert _run(monkeypatch) == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert "[refresh] 비활성 설치본, skip" in _log(cn_root)

    def test_no_session_id_returns_0_silently(self, cn_root, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert main(["--now"]) == 0
        assert capsys.readouterr().err == ""

    def test_env_session_id_fallback(self, cn_root, monkeypatch, capsys):
        _seed()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert main(["--now"]) == 2

    def test_stdin_takes_priority_over_env(self, cn_root, monkeypatch):
        _seed()
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "env-priority")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": SID})))
        main(["--now"])
        assert _marker().wake_count == 1
        assert Marker.load(sanitize("env-priority")).wake_count == 0

    def test_config_toml_auto_created(self, cn_root, monkeypatch):
        cfg = cn_root / "config.toml"
        assert not cfg.exists()
        _run(monkeypatch)
        content = cfg.read_text()
        assert "auto_wakes = 2" in content
        assert "arm" not in content

    def test_invalid_config_value_falls_back(self, cn_root, monkeypatch, capsys):
        """잘못된 auto_wakes → 기본 2 (예외로 죽지 않음)."""
        _write_config(cn_root, auto_wakes='"abc"')
        _seed(wake_count=1)
        assert _run(monkeypatch) == 2
        assert "2/2" in capsys.readouterr().err


def test_build_ping_uses_naive_local_now():
    """회귀 가드: _build_ping 이 datetime.now() naive 호출."""
    from freezegun import freeze_time
    with freeze_time("2026-05-23 03:15:00"):
        ping = _build_ping("1/2")
        assert "03:15" in ping
        assert "ok @03:15 (1/2)" in ping

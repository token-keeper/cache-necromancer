"""Tests for scripts/refresh.py (TECH_SPEC §4 + §11.1).

sleep + osascript notify 모두 monkey patch — 실제 sleep / 알림 발생 X.
"""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker, marker_path  # noqa: E402
from scripts.refresh import PING_PREFIX, main  # noqa: E402


@pytest.fixture
def fast_sleep(monkeypatch):
    """time.sleep 을 즉시 반환하도록 monkey patch."""
    monkeypatch.setattr("scripts.refresh.time.sleep", lambda s: None)


@pytest.fixture
def silent_notify(monkeypatch):
    """notify 호출 capture (osascript 실행 안 함).

    각 호출을 {"msg", "title", "subtitle", ...} dict 로 저장 — 호출 횟수
    체크는 기존처럼 len()으로 가능하고, 새 테스트에서는 메타데이터 검증 가능.
    """
    calls: list = []

    def fake(msg, **kw):
        calls.append({"msg": msg, **kw})

    monkeypatch.setattr("scripts.refresh.notify", fake)
    return calls


@pytest.fixture
def session_env(monkeypatch):
    """CLAUDE_CODE_SESSION_ID 주입 + stdin 빈 상태 (env fallback 검증용)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session-id-xyz")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    return "test-session-id-xyz"


@pytest.fixture
def session_stdin(monkeypatch):
    """stdin JSON 으로 session_id 주입 (Claude Code hook 의 실제 전달 방식)."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sid = "test-stdin-sid"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    return sid


def _write_config(cn_root, *, arm="always", notify_enabled=True,
                  refresh_interval=50, max_refresh=10, grace=60):
    cfg = cn_root / "config.toml"
    cfg.write_text(
        "[general]\n"
        f"refresh_interval_minutes = {refresh_interval}\n"
        f"max_refresh_count = {max_refresh}\n"
        f"[notify]\nenabled = {str(notify_enabled).lower()}\n"
        f'[wake]\narm = "{arm}"\ngrace_seconds = {grace}\n',
        encoding="utf-8",
    )


def _load_marker_for_sid(sid: str) -> Marker:
    from lib.session_id import sanitize
    return Marker.load(sanitize(sid))


class TestModeAuto:
    def test_auto_exits_2_and_increments_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="always", notify_enabled=False)
        rc = main()
        assert rc == 2
        # stderr 에 ping 메시지
        assert PING_PREFIX in capsys.readouterr().err
        # marker 갱신 확인
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 1
        assert m.last_wake_at > 0
        # auto mode → notify 호출 X
        assert silent_notify == []

    def test_auto_ping_includes_time_and_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        """v0.3.12: PING 에 local 시각 + 'N/M' wake 카운트 + 응답 강제 포맷.

        KST hardcode 제거 (v0.3.12) — local time 사용.
        """
        import re
        _write_config(cn_root, arm="always", notify_enabled=False, max_refresh=10)
        main()
        err = capsys.readouterr().err
        # 첫 wake 라 1/10
        assert "1/10" in err
        # KST suffix 제거됨
        assert "KST" not in err
        # HH:MM 형식 (KST suffix 없이)
        assert re.search(r"\[cn:keepalive \d{2}:\d{2}, 1/10\]", err)
        # 응답 강제 — 'ok @HH:MM (1/10)' 형식
        assert re.search(r"reply with exactly 'ok @\d{2}:\d{2} \(1/10\)'", err)

    def test_build_ping_uses_naive_local_now(self):
        """회귀 가드: _build_ping 이 datetime.now() naive 호출.

        freezegun 으로 frozen UTC 시각 고정. datetime.now() naive 면 그 시각 그대로
        반환. datetime.now(_KST) 같은 aware 호출이면 KST tz 변환되어 다른 결과.
        """
        from freezegun import freeze_time
        from scripts.refresh import _build_ping
        # frozen UTC = 2026-05-23 03:15:00. naive .now() → '03:15' 그대로.
        with freeze_time("2026-05-23 03:15:00"):
            ping = _build_ping("1/10")
            assert "03:15" in ping
            assert "ok @03:15 (1/10)" in ping
            assert "KST" not in ping


class TestModeNotify:
    def test_notify_exits_0_and_increments_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        # 구 mode="notify" → arm="manual", notify_enabled=True (budget 0 → notify only)
        _write_config(cn_root, arm="manual", notify_enabled=True)
        rc = main()
        assert rc == 0
        # stderr 에 ping 메시지 X (wake 안 했으니)
        assert PING_PREFIX not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 1
        assert m.last_wake_at > 0
        # notify 1회 호출
        assert len(silent_notify) == 1

    def test_notify_skipped_when_system_notification_false(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        """notify.enabled=false 면 알림 X + count 도 증가 X (no-op)."""
        # 구 system_notification=False → notify_enabled=False
        _write_config(cn_root, arm="manual", notify_enabled=False)
        main()
        assert silent_notify == []
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 0  # no-op — count 변경 X
        assert m.last_wake_at == 0


class TestModeHybrid:
    def test_hybrid_exits_2_after_wait_when_no_input(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        # 구 mode="hybrid" → arm="always", notify_enabled=True
        _write_config(cn_root, arm="always", notify_enabled=True)
        rc = main()
        assert rc == 2
        assert PING_PREFIX in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 1
        # always+notify → 알림 1회
        assert len(silent_notify) == 1

    def test_hybrid_skipped_when_user_input_during_wait(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        _write_config(cn_root, arm="always", notify_enabled=True, refresh_interval=50, grace=60)

        # 첫 sleep (50분) 은 통과, 두 번째 sleep (60s hybrid wait) 중 latest_fire 갱신
        sleep_count = {"n": 0}

        def fake_sleep(secs):
            sleep_count["n"] += 1
            if sleep_count["n"] == 2:
                # hybrid_wait 동안 user input 시뮬레이션 — latest_fire 갱신
                from lib.session_id import sanitize
                m = Marker.load(sanitize(session_env))
                m.latest_fire = m.latest_fire + 9999  # 미래 timestamp
                m.save()

        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0  # wake 취소
        assert PING_PREFIX not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        # wake 안 했으므로 wake_count 0
        assert m.wake_count == 0


class TestNotifyMetadata:
    """알림 본문/title/subtitle 이 세션 식별 정보를 노출하는지 검증.

    여러 chat 세션 동시 실행 시 어느 세션의 알림인지 구분 가능해야 함.
    """

    def test_notify_title_includes_project_basename(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        _write_config(cn_root, arm="manual", notify_enabled=True, max_refresh=10)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)
        m = Marker.load(sid_hash)
        m.cwd = f"{Path.home()}/work/my-project"
        m.save()

        main()
        assert len(silent_notify) == 1
        call = silent_notify[0]
        assert call["title"] == "cache-necromancer · my-project"
        # subtitle: <sid8> · (1/10)
        assert call["subtitle"].endswith(" · (1/10)")
        # body: 단축경로 + 기존 메시지
        assert "~/work/my-project — " in call["msg"]
        assert "cache 만료 임박" in call["msg"]

    def test_notify_without_cwd_falls_back(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        """cwd 비어있으면 title 은 fallback, body 에 경로 prefix 없음."""
        _write_config(cn_root, arm="manual", notify_enabled=True)
        main()
        call = silent_notify[0]
        assert call["title"] == "cache-necromancer"
        # cwd 가 없으면 "<path> — <msg>" prefix 가 붙지 않음
        # (메시지 자체에 em-dash 가 포함될 수 있으므로 ~ prefix 로 검사)
        assert not call["msg"].startswith("~")

    def test_hybrid_notify_displays_pending_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        """always+notify 는 wake 직전 알림이므로 N+1 (이번 알림이 곧 N+1번째 wake) 표시."""
        _write_config(cn_root, arm="always", notify_enabled=True, max_refresh=5)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)
        m = Marker.load(sid_hash)
        m.cwd = f"{Path.home()}/projects/foo"
        m.save()

        main()
        assert len(silent_notify) == 1
        assert silent_notify[0]["subtitle"].endswith(" · (1/5)")


class TestSkipConditions:
    def test_max_refresh_count_blocks_wake(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="always", notify_enabled=False, max_refresh=3)
        # 미리 wake_count = 3 (max 도달)
        from lib.session_id import sanitize
        m = Marker.load(sanitize(session_env))
        m.wake_count = 3
        m.save()

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        # wake_count 변경 없음 (진입부 latest_fire 갱신만)
        assert m.wake_count == 3

    def test_superseded_by_newer_fire_skips_wake(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        _write_config(cn_root, arm="always", notify_enabled=False)
        # sleep 동안 다른 hook fire → latest_fire 갱신
        def fake_sleep(secs):
            from lib.session_id import sanitize
            m = Marker.load(sanitize(session_env))
            m.latest_fire = m.latest_fire + 9999
            m.save()
        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        # 더 최근 fire 의 latest_fire 가 살아있음
        assert m.wake_count == 0  # wake skip

    def test_superseded_by_user_activity_skips_wake(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        """v0.3.15: sleep 동안 사용자가 prompt 를 쳐서 last_user_activity_at_ns
        가 my_ts 보다 늦어지면 wake 안 일어남. model 응답이 50분 넘게 진행되어
        새 Stop hook fire 가 안 들어와도 사용자 활동만으로 supersede 보장.
        """
        _write_config(cn_root, arm="always", notify_enabled=False)

        def fake_sleep(secs):
            from lib.session_id import sanitize
            m = Marker.load(sanitize(session_env))
            # latest_fire 는 그대로 (= 새 Stop hook fire 가 안 들어옴 시뮬레이션)
            # user activity 만 더 늦은 ts 로 갱신
            m.last_user_activity_at_ns = m.latest_fire + 9999
            m.save()
        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert silent_notify == []
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 0

    def test_hybrid_wait_superseded_by_user_activity_cancels_wake(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        """grace wait 중에 사용자가 prompt 를 쳐서 last_user_activity_at_ns
        갱신되면 wake 취소. 알림 자체는 첫 sleep 후 이미 발송됨.
        """
        _write_config(cn_root, arm="always", notify_enabled=True, refresh_interval=50, grace=60)

        sleep_count = {"n": 0}

        def fake_sleep(secs):
            sleep_count["n"] += 1
            if sleep_count["n"] == 2:
                # hybrid_wait 중 user activity 시뮬레이션
                from lib.session_id import sanitize
                m = Marker.load(sanitize(session_env))
                m.last_user_activity_at_ns = m.latest_fire + 9999
                m.save()

        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        # notify 는 첫 sleep 통과 직후 발송됨 (wake 만 취소)
        assert len(silent_notify) == 1
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 0

    def test_session_end_during_sleep_skips_and_no_zombie(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        """SessionEnd 가 sleep 중 발생 → wake/notify skip + 좀비 마커 재생성 X.

        회귀 가드: SessionEnd 가 마커 파일을 삭제했지만 백그라운드 refresh.py
        가 이미 sleep 중이라 살아있음. sleep 후 Marker.load 가 fresh marker
        (latest_fire=0) 를 반환 — supersede 체크가 0 > my_ts 로 False 라
        가드 없이는 wake 가 실행되고 좀비 마커가 재생성됨.
        """
        _write_config(cn_root, arm="always", notify_enabled=False)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)

        def fake_sleep(secs):
            # SessionEnd 시뮬레이션 — 마커 파일 삭제
            marker_path(sid_hash).unlink(missing_ok=True)

        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        assert silent_notify == []
        # 좀비 마커 재생성 X
        assert not marker_path(sid_hash).exists()

    def test_session_end_during_hybrid_wait_cancels_wake(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        """hybrid_wait 중 SessionEnd → wake 취소 + 좀비 마커 재생성 X.

        hybrid 첫 sleep 통과 후 notify 는 이미 발송됨. 두 번째 sleep
        (hybrid_wait) 중 SessionEnd → 좀비 wake 방지.
        """
        _write_config(cn_root, arm="always", notify_enabled=True, refresh_interval=50, grace=60)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)

        sleep_count = {"n": 0}

        def fake_sleep(secs):
            sleep_count["n"] += 1
            if sleep_count["n"] == 2:
                marker_path(sid_hash).unlink(missing_ok=True)

        monkeypatch.setattr("scripts.refresh.time.sleep", fake_sleep)

        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err
        # notify 는 첫 sleep 통과 직후 발송됨
        assert len(silent_notify) == 1
        assert not marker_path(sid_hash).exists()


class TestErrorPaths:
    def test_no_session_id_returns_0_silently(self, cn_root, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        rc = main()
        assert rc == 0
        assert capsys.readouterr().err == ""

    def test_invalid_config_returns_0(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        cfg = cn_root / "config.toml"
        cfg.write_text('[wake]\narm = "invalid"\n', encoding="utf-8")
        rc = main()
        assert rc == 0  # 그냥 종료

    def test_config_toml_auto_created_on_first_fire(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        """config.toml 없을 때 첫 hook fire 가 자동 생성 (PRD §3.2)."""
        cfg = cn_root / "config.toml"
        assert not cfg.exists()
        main()
        assert cfg.exists()
        content = cfg.read_text()
        assert "[general]" in content
        # v0.5.0: legacy mode 키 대신 [wake] arm 으로 교체
        assert "arm" in content


class TestSessionIdResolution:
    def test_stdin_session_id_used_when_env_missing(
        self, cn_root, session_stdin, fast_sleep, silent_notify, capsys
    ):
        """Claude Code hook 의 실제 패턴 — stdin JSON 으로 session_id 전달.

        이 fix 가 없으면 refresh.py 가 fire 안 됨 (env var 없음 → exit 0).
        """
        _write_config(cn_root, arm="always", notify_enabled=False)
        rc = main()
        assert rc == 2
        assert PING_PREFIX in capsys.readouterr().err
        # stdin 으로 받은 sid 의 marker 가 갱신됨
        from lib.session_id import sanitize
        m = Marker.load(sanitize(session_stdin))
        assert m.wake_count == 1

    def test_stdin_takes_priority_over_env(
        self, cn_root, monkeypatch, fast_sleep, silent_notify
    ):
        """stdin 과 env 둘 다 있으면 stdin 우선."""
        stdin_sid = "stdin-priority"
        env_sid = "env-priority"
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", env_sid)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": stdin_sid})))
        _write_config(cn_root, arm="always", notify_enabled=False)
        main()
        from lib.session_id import sanitize
        # stdin 의 marker 만 갱신됨
        assert Marker.load(sanitize(stdin_sid)).wake_count == 1
        assert Marker.load(sanitize(env_sid)).wake_count == 0

    def test_marker_save_failure_aborts_silently(
        self, cn_root, session_env, fast_sleep, silent_notify, monkeypatch
    ):
        _write_config(cn_root, arm="always", notify_enabled=False)
        # marker.save 가 항상 OSError raise
        from lib.marker import Marker as M
        def bad_save(self):
            raise OSError("simulated")
        monkeypatch.setattr(M, "save", bad_save)
        rc = main()
        assert rc == 0  # 진입부 fire save 실패 → exit 0

    def test_wake_save_failure_proceeds(
        self, cn_root, session_env, fast_sleep, silent_notify, monkeypatch, capsys
    ):
        """wake 직전 save 실패 — wake 자체는 진행 (cache 갱신 우선)."""
        _write_config(cn_root, arm="always", notify_enabled=False)
        from lib.marker import Marker as M

        original_save = M.save
        call_count = {"n": 0}

        def maybe_fail(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # 진입부 fire save 는 성공
                return original_save(self)
            # 두 번째 (wake save) 는 실패
            raise OSError("simulated wake save fail")

        monkeypatch.setattr(M, "save", maybe_fail)
        rc = main()
        # save 실패에도 wake 진행 (PING_PREFIX 발송 + exit 2)
        assert rc == 2
        assert PING_PREFIX in capsys.readouterr().err


class TestKillOlderBuddies:
    """_kill_older_buddies() — 자기보다 옛날 버전의 refresh.py SIGTERM."""

    @pytest.fixture
    def kill_capture(self, monkeypatch):
        """os.kill 호출을 (pid, sig) 리스트로 capture."""
        calls = []
        monkeypatch.setattr("scripts.refresh.os.kill", lambda p, s: calls.append((p, s)))
        return calls

    @pytest.fixture
    def fake_pgrep(self, monkeypatch):
        """pgrep stdout 주입 + 예외 주입 (state['raise'])."""
        state = {"stdout": "", "raise": None}

        def fake_run(*args, **kwargs):
            if state["raise"] is not None:
                raise state["raise"]

            class R:
                pass
            R.stdout = state["stdout"]
            return R()

        monkeypatch.setattr("scripts.refresh.subprocess.run", fake_run)
        return state

    @staticmethod
    def _set_my_version(monkeypatch, version: str, pid: int = 99):
        from pathlib import Path as _P
        monkeypatch.setattr(
            "scripts.refresh._HERE",
            _P(f"/fake/cache-necromancer/{version}/scripts"),
        )
        monkeypatch.setattr("scripts.refresh.os.getpid", lambda: pid)

    def test_older_buddies_killed(self, monkeypatch, kill_capture, fake_pgrep):
        import signal as _sig
        from scripts.refresh import _kill_older_buddies
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["stdout"] = (
            "100 python3 cache-necromancer/0.4.0/scripts/refresh.py\n"
            "101 python3 cache-necromancer/0.3.13/scripts/refresh.py\n"
        )
        _kill_older_buddies()
        assert sorted(kill_capture) == [(100, _sig.SIGTERM), (101, _sig.SIGTERM)]

    def test_same_or_newer_not_killed(self, monkeypatch, kill_capture, fake_pgrep):
        from scripts.refresh import _kill_older_buddies
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["stdout"] = (
            "200 python3 cache-necromancer/0.4.2/scripts/refresh.py\n"
            "201 python3 cache-necromancer/0.5.0/scripts/refresh.py\n"
            "202 python3 cache-necromancer/0.10.0/scripts/refresh.py\n"
        )
        _kill_older_buddies()
        assert kill_capture == []

    def test_self_pid_skipped(self, monkeypatch, kill_capture, fake_pgrep):
        import signal as _sig
        from scripts.refresh import _kill_older_buddies
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["stdout"] = (
            "99 python3 cache-necromancer/0.4.0/scripts/refresh.py\n"
            "100 python3 cache-necromancer/0.4.0/scripts/refresh.py\n"
        )
        _kill_older_buddies()
        assert kill_capture == [(100, _sig.SIGTERM)]

    def test_subprocess_error_silent(self, monkeypatch, kill_capture, fake_pgrep):
        import subprocess as _sp
        from scripts.refresh import _kill_older_buddies
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["raise"] = _sp.SubprocessError("boom")
        _kill_older_buddies()
        assert kill_capture == []

    def test_pgrep_missing_silent(self, monkeypatch, kill_capture, fake_pgrep):
        from scripts.refresh import _kill_older_buddies
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["raise"] = FileNotFoundError("no pgrep")
        _kill_older_buddies()
        assert kill_capture == []

    def test_os_kill_failure_silent(self, monkeypatch, fake_pgrep):
        """os.kill 이 OSError 발생해도 silent 진행."""
        from scripts.refresh import _kill_older_buddies
        attempts = []

        def fake_kill(pid, sig):
            attempts.append(pid)
            raise ProcessLookupError("dead already")

        monkeypatch.setattr("scripts.refresh.os.kill", fake_kill)
        self._set_my_version(monkeypatch, "0.4.2", pid=99)
        fake_pgrep["stdout"] = (
            "100 python3 cache-necromancer/0.4.0/scripts/refresh.py\n"
            "101 python3 cache-necromancer/0.3.13/scripts/refresh.py\n"
        )
        _kill_older_buddies()  # 예외 X
        assert sorted(attempts) == [100, 101]

    def test_dev_environment_skips_pgrep(self, monkeypatch, kill_capture):
        """parents[1] 이 version 패턴 아니면 pgrep 호출 자체 X."""
        from pathlib import Path as _P
        from scripts.refresh import _kill_older_buddies

        def must_not_call(*a, **kw):
            raise AssertionError("subprocess.run must not be called in dev env")

        monkeypatch.setattr(
            "scripts.refresh._HERE",
            _P("/fake/cache-necromancer/scripts"),
        )
        monkeypatch.setattr("scripts.refresh.subprocess.run", must_not_call)
        _kill_older_buddies()
        assert kill_capture == []


class TestManualArm:
    def test_unarmed_notify_enabled_sends_notification_only(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="manual", notify_enabled=True)
        rc = main()
        assert rc == 0
        assert len(silent_notify) == 1
        assert "/cn:set" in silent_notify[0]["msg"]
        assert PING_PREFIX not in capsys.readouterr().err

    def test_unarmed_notify_disabled_is_noop(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="manual", notify_enabled=False)
        rc = main()
        assert rc == 0
        assert silent_notify == []
        assert PING_PREFIX not in capsys.readouterr().err

    def test_armed_wakes_and_decrements_budget(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="manual", notify_enabled=False)
        from lib.session_id import sanitize
        m = Marker.load(sanitize(session_env))
        m.set_budget_remaining = 2
        m.set_budget_total = 2
        m.save()
        rc = main()
        assert rc == 2
        err = capsys.readouterr().err
        assert "(1/2)" in err                  # consumed/total (codex F2)
        m2 = _load_marker_for_sid(session_env)
        assert m2.set_budget_remaining == 1    # ping 출력 전 저장됨

    def test_budget_charged_during_sleep_is_consumed(
        self, cn_root, session_env, silent_notify, monkeypatch, capsys
    ):
        """sleep 시작 시 예산 0 → sleep 중 /cn:set 충전 → wake (codex F1)."""
        _write_config(cn_root, arm="manual", notify_enabled=False)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)

        def charge_during_sleep(seconds):
            m = Marker.load(sid_hash)
            m.set_budget_remaining = 1
            m.set_budget_total = 1
            m.save()

        monkeypatch.setattr("scripts.refresh.time.sleep", charge_during_sleep)
        rc = main()
        assert rc == 2
        assert "(1/1)" in capsys.readouterr().err

    def test_last_budget_consumed_then_next_fire_notifies_only(
        self, cn_root, session_env, fast_sleep, silent_notify, monkeypatch, capsys
    ):
        """예산 1 → wake 후 0 → 다음 fire 는 알림만 ("2번 fire되고 마는거임")."""
        import io
        _write_config(cn_root, arm="manual", notify_enabled=True)
        from lib.session_id import sanitize
        m = Marker.load(sanitize(session_env))
        m.set_budget_remaining = 1
        m.set_budget_total = 1
        m.save()
        assert main() == 2                      # wake (예산 소진)
        capsys.readouterr()
        monkeypatch.setattr("sys.stdin", io.StringIO(""))  # stdin 재주입 (env fallback)
        assert main() == 0                      # 알림만
        assert any("/cn:set" in c["msg"] for c in silent_notify)

    def test_grace_recheck_cancels_when_budget_zeroed(
        self, cn_root, session_env, silent_notify, monkeypatch, capsys
    ):
        """grace 대기 중 복귀(예산 0 처리) → wake 취소."""
        _write_config(cn_root, arm="manual", notify_enabled=True, grace=60)
        from lib.session_id import sanitize
        sid_hash = sanitize(session_env)
        m = Marker.load(sid_hash)
        m.set_budget_remaining = 1
        m.set_budget_total = 1
        m.save()
        calls = {"n": 0}

        def sleep_then_zero(seconds):
            calls["n"] += 1
            if calls["n"] == 2:                 # 두 번째 sleep = grace 대기
                m2 = Marker.load(sid_hash)
                m2.set_budget_remaining = 0
                m2.save()

        monkeypatch.setattr("scripts.refresh.time.sleep", sleep_then_zero)
        rc = main()
        assert rc == 0
        assert PING_PREFIX not in capsys.readouterr().err


class TestAlwaysArmKeepsLegacyBehavior:
    def test_always_ping_uses_wake_count_over_max(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, arm="always", notify_enabled=False, max_refresh=10)
        rc = main()
        assert rc == 2
        assert "(1/10)" in capsys.readouterr().err

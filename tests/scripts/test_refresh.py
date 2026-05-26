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


def _write_config(cn_root, *, mode="auto", refresh_interval=50, max_refresh=10,
                  hybrid_wait=60, system_notification=True):
    cfg = cn_root / "config.toml"
    cfg.write_text(
        f'[general]\nmode = "{mode}"\n'
        f"refresh_interval_minutes = {refresh_interval}\n"
        f"max_refresh_count = {max_refresh}\n"
        f"[notify]\nsystem_notification = {str(system_notification).lower()}\n"
        f"[refresh]\nhybrid_wait_seconds = {hybrid_wait}\n",
        encoding="utf-8",
    )


def _load_marker_for_sid(sid: str) -> Marker:
    from lib.session_id import sanitize
    return Marker.load(sanitize(sid))


class TestModeAuto:
    def test_auto_exits_2_and_increments_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, mode="auto")
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
        _write_config(cn_root, mode="auto", max_refresh=10)
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
            ping = _build_ping(1, 10)
            assert "03:15" in ping
            assert "ok @03:15 (1/10)" in ping
            assert "KST" not in ping


class TestModeNotify:
    def test_notify_exits_0_and_increments_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, mode="notify")
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
        """system_notification=false 면 알림 X + count 도 증가 X (no-op)."""
        _write_config(cn_root, mode="notify", system_notification=False)
        main()
        assert silent_notify == []
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 0  # no-op — count 변경 X
        assert m.last_wake_at == 0


class TestModeHybrid:
    def test_hybrid_exits_2_after_wait_when_no_input(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, mode="hybrid")
        rc = main()
        assert rc == 2
        assert PING_PREFIX in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 1
        # hybrid → 알림 1회
        assert len(silent_notify) == 1

    def test_hybrid_skipped_when_user_input_during_wait(
        self, cn_root, session_env, monkeypatch, silent_notify, capsys
    ):
        _write_config(cn_root, mode="hybrid", refresh_interval=50, hybrid_wait=60)

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
        _write_config(cn_root, mode="notify", max_refresh=10)
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
        """cwd 비어있으면 title 은 fallback, body prefix 없음."""
        _write_config(cn_root, mode="notify")
        main()
        call = silent_notify[0]
        assert call["title"] == "cache-necromancer"
        assert "—" not in call["msg"]

    def test_hybrid_notify_displays_pending_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify
    ):
        """hybrid 는 wake 직전 알림이므로 N+1 (이번 알림이 곧 N+1번째 wake) 표시."""
        _write_config(cn_root, mode="hybrid", max_refresh=5)
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
        _write_config(cn_root, mode="auto", max_refresh=3)
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
        _write_config(cn_root, mode="auto")
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
        _write_config(cn_root, mode="auto")

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
        """hybrid wait 중에 사용자가 prompt 를 쳐서 last_user_activity_at_ns
        갱신되면 wake 취소. 알림 자체는 첫 sleep 후 이미 발송됨.
        """
        _write_config(cn_root, mode="hybrid", refresh_interval=50, hybrid_wait=60)

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
        _write_config(cn_root, mode="auto")
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
        _write_config(cn_root, mode="hybrid", refresh_interval=50, hybrid_wait=60)
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
        cfg.write_text('[general]\nmode = "invalid"\n', encoding="utf-8")
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
        assert "mode" in content


class TestSessionIdResolution:
    def test_stdin_session_id_used_when_env_missing(
        self, cn_root, session_stdin, fast_sleep, silent_notify, capsys
    ):
        """Claude Code hook 의 실제 패턴 — stdin JSON 으로 session_id 전달.

        이 fix 가 없으면 refresh.py 가 fire 안 됨 (env var 없음 → exit 0).
        """
        _write_config(cn_root, mode="auto")
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
        _write_config(cn_root, mode="auto")
        main()
        from lib.session_id import sanitize
        # stdin 의 marker 만 갱신됨
        assert Marker.load(sanitize(stdin_sid)).wake_count == 1
        assert Marker.load(sanitize(env_sid)).wake_count == 0

    def test_marker_save_failure_aborts_silently(
        self, cn_root, session_env, fast_sleep, silent_notify, monkeypatch
    ):
        _write_config(cn_root, mode="auto")
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
        _write_config(cn_root, mode="auto")
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

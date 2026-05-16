"""Tests for scripts/refresh.py (TECH_SPEC §4 + §11.1).

sleep + osascript notify 모두 monkey patch — 실제 sleep / 알림 발생 X.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker  # noqa: E402
from scripts.refresh import PING_MESSAGE, main  # noqa: E402


@pytest.fixture
def fast_sleep(monkeypatch):
    """time.sleep 을 즉시 반환하도록 monkey patch."""
    monkeypatch.setattr("scripts.refresh.time.sleep", lambda s: None)


@pytest.fixture
def silent_notify(monkeypatch):
    """notify 호출 capture (osascript 실행 안 함)."""
    calls: list = []
    monkeypatch.setattr("scripts.refresh.notify", lambda msg, **kw: calls.append(msg))
    return calls


@pytest.fixture
def session_env(monkeypatch):
    """CLAUDE_CODE_SESSION_ID 주입."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session-id-xyz")
    return "test-session-id-xyz"


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
        assert PING_MESSAGE in capsys.readouterr().err
        # marker 갱신 확인
        m = _load_marker_for_sid(session_env)
        assert m.wake_count == 1
        assert m.last_wake_at > 0
        # auto mode → notify 호출 X
        assert silent_notify == []


class TestModeNotify:
    def test_notify_exits_0_and_increments_wake_count(
        self, cn_root, session_env, fast_sleep, silent_notify, capsys
    ):
        _write_config(cn_root, mode="notify")
        rc = main()
        assert rc == 0
        # stderr 에 ping 메시지 X (wake 안 했으니)
        assert PING_MESSAGE not in capsys.readouterr().err
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
        assert PING_MESSAGE in capsys.readouterr().err
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
        assert PING_MESSAGE not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        # wake 안 했으므로 wake_count 0
        assert m.wake_count == 0


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
        assert PING_MESSAGE not in capsys.readouterr().err
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
        assert PING_MESSAGE not in capsys.readouterr().err
        m = _load_marker_for_sid(session_env)
        # 더 최근 fire 의 latest_fire 가 살아있음
        assert m.wake_count == 0  # wake skip


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
        # save 실패에도 wake 진행 (PING_MESSAGE 발송 + exit 2)
        assert rc == 2
        assert PING_MESSAGE in capsys.readouterr().err

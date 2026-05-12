"""폴링 루프 + 후보 판정 (notify 모드 only — Phase 1b 범위).

fire 호출 / auto / hybrid 모드는 Phase 2에서 추가된다.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.config import Config
from lib.state import parse_iso, update_state, load_all_states

from daemon import notifier
from daemon.clock import DriftDetector
from lib.logger import log_info, log_warn

import time as _time


def is_refresh_candidate(s: dict, now: datetime, config: Config) -> bool:
    """fire 후보 판정 (전부 AND).

    조건:
    - ``disabled=False``
    - ``next_refresh_at`` 가 ``now`` 도달
    - ``refresh_count < max_refresh_count``
    - ``backoff_until`` 가 ``now`` 도달 (또는 None)
    - ``current_turn_started_at`` 가 None (사용자 turn 진행 중 아님)
    - 사용자 input 후 ``interactive_input_quiet_seconds`` 경과
    """
    if s.get("disabled"):
        return False

    next_at = parse_iso(s.get("next_refresh_at"))
    if next_at is None or now < next_at:
        return False

    if s.get("refresh_count", 0) >= config.max_refresh_count:
        return False

    backoff_until = parse_iso(s.get("backoff_until"))
    if backoff_until is not None and now < backoff_until:
        return False

    if s.get("current_turn_started_at") is not None:
        return False

    last_input = parse_iso(s.get("last_user_input_at"))
    if last_input is not None:
        quiet = config.advanced.interactive_input_quiet_seconds
        if (now - last_input).total_seconds() < quiet:
            return False

    return True


def min_next_fire_in(
    sessions: list[dict], now: datetime, config: Config
) -> float:
    """모든 세션의 ``next_refresh_at - now`` 양의 최솟값. 없으면 daemon_poll_max."""
    cap = float(config.advanced.daemon_poll_max_seconds)
    best: Optional[float] = None
    for s in sessions:
        next_at = parse_iso(s.get("next_refresh_at"))
        if next_at is None:
            continue
        delta = (next_at - now).total_seconds()
        if delta <= 0:
            continue
        if best is None or delta < best:
            best = delta
    return best if best is not None else cap


def all_stale_for(
    sessions: list[dict],
    *,
    minutes: int,
    now: Optional[datetime] = None,
) -> bool:
    """모든 세션이 ``minutes`` 이상 무활동이면 True. 빈 리스트는 False."""
    if not sessions:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=minutes)
    for s in sessions:
        recent = parse_iso(s.get("last_stop_at")) or parse_iso(s.get("last_user_input_at"))
        if recent is None:
            return False  # 신규 세션도 stale 아님
        if recent > cutoff:
            return False
    return True


def _notify_imminent(s: dict, now: datetime, config: Config) -> None:
    """imminent 알림 발사 + imminent_notified=True 마킹."""
    sid_short = s.get("session_id", "")[:8] or s.get("sid_hash", "")[:8]
    notifier.notify(
        f"💀 {sid_short} 캐시 만료 임박",
        terminal_bell=config.notify.terminal_bell,
        system_notification=config.notify.system_notification,
    )
    log_info(f"[imminent] sid={s.get('sid_hash')}")
    update_state(
        s["sid_hash"],
        lambda x: {**x, "imminent_notified": True},
        allow_create=False,
    )


def handle_session(s: dict, now: datetime, config: Config) -> None:
    """단일 세션 처리. notify 모드만 (Phase 1b 범위).

    - 후보 아니면: ``next_refresh_at - imminent_threshold_minutes`` 이내고
      아직 알림 안 했으면 imminent 알림 발사.
    - 후보면: mode에 따라 분기 (현재는 notify만).
    """
    if not is_refresh_candidate(s, now, config):
        # 임박 알림 확인
        next_at = parse_iso(s.get("next_refresh_at"))
        if next_at is None or s.get("imminent_notified"):
            return
        imminent_at = next_at - timedelta(
            minutes=config.notify.imminent_threshold_minutes
        )
        if now >= imminent_at:
            _notify_imminent(s, now, config)
        return

    # 후보 도달 — mode 분기
    if config.mode == "notify":
        if s.get("imminent_notified"):
            return  # 이미 알림 보냄
        sid_short = s.get("session_id", "")[:8] or s.get("sid_hash", "")[:8]
        notifier.notify(
            f"💀 {sid_short} 캐시 갱신 시점 도달 (notify only)",
            terminal_bell=config.notify.terminal_bell,
            system_notification=config.notify.system_notification,
        )
        log_info(f"[would-fire] sid={s.get('sid_hash')} mode=notify")
        update_state(
            s["sid_hash"],
            lambda x: {**x, "imminent_notified": True},
            allow_create=False,
        )
    else:
        # auto / hybrid 는 Phase 2에서 추가
        log_warn(
            f"[mode-not-implemented] sid={s.get('sid_hash')} mode={config.mode} "
            f"(Phase 2 미구현, notify로 fallback)"
        )
        update_state(
            s["sid_hash"],
            lambda x: {**x, "imminent_notified": True},
            allow_create=False,
        )


def run_poll_loop(config: Config) -> None:
    """폴링 메인 루프.

    - 매 사이클: state 수집 → 세션별 handle → idle shutdown 체크 → 동적 sleep + drift 감지
    - 모든 세션 ``daemon_idle_shutdown_minutes`` 이상 무활동이면 데몬 자체 종료.
    """
    detector = DriftDetector(
        threshold_seconds=config.advanced.clock_drift_threshold_seconds
    )

    log_info("[daemon] poll loop start")
    while True:
        sessions = load_all_states()
        if not sessions:
            log_info("[daemon] no sessions; shutting down")
            return

        now = datetime.now(timezone.utc)

        for s in sessions:
            handle_session(s, now, config)

        if all_stale_for(
            sessions,
            minutes=config.advanced.daemon_idle_shutdown_minutes,
            now=now,
        ):
            log_info("[daemon] all sessions idle; shutting down")
            return

        sleep_seconds = max(
            1.0,
            min(
                float(config.advanced.daemon_poll_max_seconds),
                min_next_fire_in(sessions, now, config),
            ),
        )

        detector.mark_sleep_start(sleep_seconds)
        _time.sleep(sleep_seconds)
        drift = detector.detect_after_sleep()
        if drift > 0:
            log_warn(f"[daemon] sleep/wake drift={drift}s — postpone 5min")
            _postpone_all(
                sessions, minutes=config.advanced.clock_drift_postpone_minutes
            )


def _postpone_all(sessions: list[dict], *, minutes: int) -> None:
    """모든 세션의 next_refresh_at을 +minutes 미래로 미룸 (sleep/wake 보정)."""
    now = datetime.now(timezone.utc)
    delta = timedelta(minutes=minutes)
    for s in sessions:
        sid = s.get("sid_hash")
        if not sid:
            continue
        update_state(
            sid,
            lambda x, d=delta: {
                **x,
                "next_refresh_at": (
                    (parse_iso(x.get("next_refresh_at")) or now) + d
                ).isoformat()
                if x.get("next_refresh_at") is not None
                else None,
            },
            allow_create=False,
        )

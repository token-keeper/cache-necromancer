"""폴링 루프 + 후보 판정 (notify 모드 only — Phase 1b 범위).

fire 호출 / auto / hybrid 모드는 Phase 2에서 추가된다. Phase 1b 동안
사용자가 ``mode=hybrid`` 또는 ``auto`` 로 설정해도 notify 동작으로
fallback해 알림은 반드시 발사된다 (silent failure 차단).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.config import Config
from lib.plugin_state import is_plugin_active
from lib.state import parse_iso, update_state, load_all_states

from daemon import notifier, scheduler, watchdog
from daemon.clock import DriftDetector
from lib.logger import log_info, log_warn

import time as _time


def _safe_parse_iso(s: dict, field: str) -> Optional[datetime]:
    """state의 timestamp 필드를 안전하게 파싱.

    malformed 값을 만나면 None을 반환하고 한 줄 경고를 남긴다 (해당 세션
    하나의 corrupt가 poll loop 전체를 죽이는 사고 방지).
    """
    raw = s.get(field)
    if raw is None:
        return None
    try:
        return parse_iso(raw)
    except (ValueError, TypeError):
        log_warn(
            f"[poller] malformed {field}: sid={s.get('sid_hash')} value={raw!r}"
        )
        return None


def is_refresh_candidate(s: dict, now: datetime, config: Config) -> bool:
    """fire 후보 판정 (전부 AND).

    조건:
    - ``disabled=False``
    - ``next_refresh_at`` 가 ``now`` 도달
    - ``refresh_count < max_refresh_count``
    - ``backoff_until`` 가 ``now`` 도달 (또는 None)
    - ``current_turn_started_at`` 가 None (사용자 turn 진행 중 아님)
    - 사용자 input 후 ``interactive_input_quiet_seconds`` 경과

    malformed timestamp는 ``_safe_parse_iso`` 가 log + None 처리 → 보수적
    분기(후보 아님)로 흐른다. poll loop 전체가 죽지 않는다.
    """
    if s.get("disabled"):
        return False

    next_at = _safe_parse_iso(s, "next_refresh_at")
    if next_at is None or now < next_at:
        return False

    if s.get("refresh_count", 0) >= config.max_refresh_count:
        return False

    backoff_until = _safe_parse_iso(s, "backoff_until")
    if backoff_until is not None and now < backoff_until:
        return False

    if s.get("current_turn_started_at") is not None:
        return False

    last_input = _safe_parse_iso(s, "last_user_input_at")
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
        next_at = _safe_parse_iso(s, "next_refresh_at")
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
        recent = (
            _safe_parse_iso(s, "last_stop_at")
            or _safe_parse_iso(s, "last_user_input_at")
        )
        if recent is None:
            return False  # 신규 세션도 stale 아님
        if recent > cutoff:
            return False
    return True


def _mark_imminent_notified(sid_hash: str, *, where: str) -> None:
    """imminent_notified=True 마킹. update_state OSError는 daemon 중단 방지 위해 흡수."""
    try:
        update_state(
            sid_hash,
            lambda x: {**x, "imminent_notified": True},
            allow_create=False,
        )
    except OSError as e:
        log_warn(f"[poller] update_state failed ({where}) sid={sid_hash} err={e}")


def _notify_imminent(s: dict, now: datetime, config: Config) -> None:
    """imminent 알림 발사 + imminent_notified=True 마킹."""
    sid_short = s.get("session_id", "")[:8] or s.get("sid_hash", "")[:8]
    notifier.notify(
        f"💀 {sid_short} 캐시 만료 임박",
        terminal_bell=config.notify.terminal_bell,
        system_notification=config.notify.system_notification,
    )
    log_info(f"[imminent] sid={s.get('sid_hash')}")
    _mark_imminent_notified(s["sid_hash"], where="imminent")


def handle_session(s: dict, now: datetime, config: Config) -> None:
    """단일 세션 처리.

    - 후보 아니면: ``next_refresh_at - imminent_threshold_minutes`` 이내고
      아직 알림 안 했으면 imminent 알림 발사.
    - 후보면: ``scheduler.execute_mode`` 로 위임 (notify / auto / hybrid).
    """
    if not is_refresh_candidate(s, now, config):
        next_at = _safe_parse_iso(s, "next_refresh_at")
        if next_at is None or s.get("imminent_notified"):
            return
        imminent_at = next_at - timedelta(
            minutes=config.notify.imminent_threshold_minutes
        )
        if now >= imminent_at:
            _notify_imminent(s, now, config)
        return

    scheduler.execute_mode(s, config)


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
        if not is_plugin_active():
            log_info("[daemon] plugin disabled; shutting down")
            return

        sessions = load_all_states()
        if not sessions:
            log_info("[daemon] no sessions; shutting down")
            return

        now = datetime.now(timezone.utc)

        # watchdog: fire→Stop 누락 세션 복구 (다른 처리보다 먼저 실행).
        # 어떤 세션이라도 복구됐으면 sessions snapshot이 stale 하므로 재로드해
        # handle_session 이 갱신된 next_refresh_at 으로 동작하게 한다.
        recovered = False
        for s in sessions:
            if watchdog.watchdog_check(s, now, config):
                recovered = True
        if recovered:
            sessions = load_all_states()
            if not sessions:
                log_info("[daemon] no sessions after watchdog; shutting down")
                return

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
    """모든 세션의 next_refresh_at을 +minutes 미래로 미룸 (sleep/wake 보정).

    malformed timestamp는 ``_safe_parse_iso`` 가 log + None 처리. update_state
    OSError는 흡수해 한 세션 실패가 전체 loop를 죽이지 않게 한다.
    """
    delta = timedelta(minutes=minutes)

    def _build_mutator(d: timedelta):
        def _mut(x: dict) -> dict:
            base = _safe_parse_iso(x, "next_refresh_at")
            if base is None:
                return x
            return {**x, "next_refresh_at": (base + d).isoformat()}

        return _mut

    mutator = _build_mutator(delta)
    for s in sessions:
        sid = s.get("sid_hash")
        if not sid:
            continue
        try:
            update_state(sid, mutator, allow_create=False)
        except OSError as e:
            log_warn(f"[poller] postpone failed sid={sid} err={e}")

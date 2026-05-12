"""fire 결과 후처리 — handle_fire_result + _backoff_seconds.

성공 시 next_refresh_at을 데몬이 직접 갱신 (headless fire는 Stop hook을 만들지
않으므로 자동 갱신 안 됨). 실패는 reason별 분기:
- AUTH_ERROR (PERMANENT) → 즉시 disable_session
- CACHE_COLD → cache_cold_retries++, max 도달 시 disable, 미달 시 backoff
- TRANSIENT (NETWORK_ERROR / TIMEOUT / PROCESS_ERROR / BAD_OUTPUT) →
  consecutive_fire_failures++, backoff. 3회면 알림, 5회면 disable.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from daemon import notifier
from daemon.refresh import (
    FireReason,
    FireResult,
    PERMANENT_REASONS,
    TRANSIENT_REASONS,
    disable_session,
)
from lib.logger import log_fire, log_warn
from lib.state import update_state


def _backoff_seconds(
    failure_count: int,
    base: float = 30.0,
    cap: float = 1800.0,
) -> float:
    """exponential backoff with ±25% jitter.

    1회 base*1, 2회 base*2, ... cap에서 절단. 결과에 0.5~1.0 multiplier 적용.
    """
    exp = min(cap, base * (2 ** max(0, failure_count - 1)))
    jitter = 0.5 + random.random() * 0.5
    return exp * jitter


def _sid_short(s: dict) -> str:
    return (s.get("session_id") or s.get("sid_hash") or "")[:8]


def handle_fire_result(s: dict, result: FireResult, config) -> None:
    """fire 결과를 받아 state / scheduler / 알림 / disable 분기.

    update_state OSError는 흡수 — daemon 보호. 다음 poll cycle에서 재시도.
    """
    max_fail = config.advanced.consecutive_fire_failures_disable
    max_cold = config.advanced.cache_cold_max_retries
    refresh_min = config.refresh_interval_minutes
    base = config.advanced.backoff_base_seconds
    cap = config.advanced.backoff_cap_seconds
    now = datetime.now(timezone.utc)

    log_fire(
        sid_hash=s.get("sid_hash", ""),
        session_id=s.get("session_id"),
        model=result.model,
        reason=result.reason.value,
        cache_read=result.cache_read,
        cache_create=result.cache_create,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        now=now,
    )

    if result.success:
        next_at = (now + timedelta(minutes=refresh_min)).isoformat()
        last_fire = now.isoformat()
        try:
            update_state(
                s["sid_hash"],
                lambda x: {
                    **x,
                    "refresh_count": x.get("refresh_count", 0) + 1,
                    "next_refresh_at": next_at,
                    "last_fire_at": last_fire,
                    "imminent_notified": False,
                    "consecutive_fire_failures": 0,
                    "cache_cold_retries": 0,
                    "backoff_until": None,
                    "last_fire_reason": result.reason.value,
                },
                allow_create=False,
            )
        except OSError as e:
            log_warn(
                f"[handler] handle_fire_result success update_state failed "
                f"sid={s.get('sid_hash')} err={e}"
            )
        return

    # 영구 실패 — AUTH_ERROR
    if result.reason in PERMANENT_REASONS:
        disable_session(
            s,
            reason=result.reason.value,
            message=(
                f"🛑 cache-necromancer: {_sid_short(s)} "
                "인증 오류로 비활성화. `/cn:status` 로 확인."
            ),
        )
        return

    # CACHE_COLD — 1회 retry 허용 → max 도달 시 disable
    if result.reason is FireReason.CACHE_COLD:
        new_retries = s.get("cache_cold_retries", 0) + 1
        if new_retries >= max_cold:
            disable_session(
                s,
                reason="cache_cold_persistent",
                message=(
                    f"💀 cache-necromancer: {_sid_short(s)} "
                    "캐시가 계속 cold 상태. 비활성화. `/cn:status` 로 확인."
                ),
            )
            return
        backoff = _backoff_seconds(new_retries, base=120.0, cap=600.0)
        log_warn(
            f"[cache_cold] sid={s.get('sid_hash')} "
            f"retry {new_retries}/{max_cold} in {backoff:.0f}s"
        )
        backoff_iso = (now + timedelta(seconds=backoff)).isoformat()
        try:
            update_state(
                s["sid_hash"],
                lambda x: {
                    **x,
                    "cache_cold_retries": new_retries,
                    "backoff_until": backoff_iso,
                    "last_fire_reason": result.reason.value,
                },
                allow_create=False,
            )
        except OSError as e:
            log_warn(
                f"[handler] cache_cold update_state failed "
                f"sid={s.get('sid_hash')} err={e}"
            )
        return

    # 일시적 실패 (TRANSIENT) — exponential backoff + counter
    if result.reason in TRANSIENT_REASONS:
        new_count = s.get("consecutive_fire_failures", 0) + 1
        backoff = _backoff_seconds(new_count, base=base, cap=cap)
        backoff_iso = (now + timedelta(seconds=backoff)).isoformat()
        try:
            update_state(
                s["sid_hash"],
                lambda x: {
                    **x,
                    "consecutive_fire_failures": new_count,
                    "backoff_until": backoff_iso,
                    "last_fire_reason": result.reason.value,
                },
                allow_create=False,
            )
        except OSError as e:
            log_warn(
                f"[handler] transient update_state failed "
                f"sid={s.get('sid_hash')} err={e}"
            )

        if new_count == 3:
            notifier.notify(
                f"⚠️ cache-necromancer: {_sid_short(s)} 3회 연속 실패 "
                f"({result.reason.value}). 다음 시도까지 {backoff:.0f}s."
            )
        if new_count >= max_fail:
            disable_session(
                s,
                reason=f"consecutive_failures_{result.reason.value}",
                message=(
                    f"🛑 cache-necromancer: {_sid_short(s)} "
                    f"{max_fail}회 연속 실패로 비활성화. `/cn:status` 로 확인."
                ),
            )
        return

    # 도달 안 함 — 모든 reason 분기 처리 완료
    log_warn(
        f"[handler] unhandled reason sid={s.get('sid_hash')} "
        f"reason={result.reason}"
    )

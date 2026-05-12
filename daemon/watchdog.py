"""fire→Stop 누락 복구 — auto/hybrid 모드 예외 안전망.

성공 fire 후 보통 ``handle_fire_result`` 가 ``next_refresh_at`` 을 직접 갱신하지만,
- 응답 도중 Claude API 오류 등으로 fire 호출 자체가 비정상 종료
- 또는 update_state OSError 흡수로 갱신 실패

같은 드문 케이스에 ``next_refresh_at=None`` 으로 영원히 정지 가능. watchdog 은
``last_fire_at`` 만 채워진 채 ``fire_stop_watchdog_seconds`` (기본 120s) 경과 시
``next_refresh_at`` 만 다시 미래로 복구. ``refresh_count`` 는 건들지 않음.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from lib.config import Config
from lib.logger import log_warn
from lib.state import parse_iso, update_state


def _safe_parse_iso(s: dict, field: str) -> Optional[datetime]:
    raw = s.get(field)
    if raw is None:
        return None
    try:
        return parse_iso(raw)
    except (ValueError, TypeError):
        return None


def watchdog_check(s: dict, now: datetime, config: Config) -> bool:
    """누락된 fire→Stop 흐름 복구.

    조건:
    - ``next_refresh_at`` 이 None
    - ``last_fire_at`` 이 채워짐
    - 경과 시간 > ``fire_stop_watchdog_seconds``

    return: state를 갱신했으면 True (caller 가 sessions 재로드 결정에 활용).
    """
    if s.get("next_refresh_at") is not None:
        return False
    last_fire = _safe_parse_iso(s, "last_fire_at")
    if last_fire is None:
        return False
    elapsed = (now - last_fire).total_seconds()
    threshold = config.advanced.fire_stop_watchdog_seconds
    if elapsed <= threshold:
        return False

    log_warn(
        f"[watchdog] fire→Stop missing for {elapsed:.0f}s, "
        f"recovering sid={s.get('sid_hash')}"
    )
    next_iso = (
        now + timedelta(minutes=config.refresh_interval_minutes)
    ).isoformat()

    def _mut(x: dict) -> dict:
        return {
            **x,
            "next_refresh_at": next_iso,
            "last_fire_at": None,
            "imminent_notified": False,
        }

    try:
        update_state(s["sid_hash"], _mut, allow_create=False)
        return True
    except OSError as e:
        log_warn(
            f"[watchdog] update_state failed sid={s.get('sid_hash')} err={e}"
        )
        return False

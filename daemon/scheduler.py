"""모드별 실행 — execute_mode + sleep_with_cancel.

후보 도달 시 호출되어 mode (notify / auto / hybrid) 에 따라:
- notify: 알림만 + imminent_notified=True
- auto: refresh.fire + handle_fire_result
- hybrid: 알림 + hybrid_wait_seconds 대기 (user input 시 취소) → fire

hybrid의 sleep은 1초 단위 폴링으로 user input 감지. 그 동안 daemon poll loop가
잠시 blocked 되지만, 다른 세션은 그 사이 next_refresh_at 변화 없음 (사용자가
다른 세션에 입력하면 그 세션은 이번 사이클 후보 아님으로 빠짐).
"""
from __future__ import annotations

import time

from daemon import handler, notifier, refresh
from lib.logger import log_info
from lib.state import load_state, parse_iso, update_state


def execute_mode(s: dict, config) -> None:
    mode = config.mode

    if mode == "notify":
        if s.get("imminent_notified"):
            return
        sid_short = (s.get("session_id") or s.get("sid_hash") or "")[:8]
        notifier.notify(
            f"💀 {sid_short} 캐시 갱신 시점 도달 (notify only)",
            terminal_bell=config.notify.terminal_bell,
            system_notification=config.notify.system_notification,
        )
        log_info(f"[would-fire] sid={s.get('sid_hash')} mode=notify")
        try:
            update_state(
                s["sid_hash"],
                lambda x: {**x, "imminent_notified": True},
                allow_create=False,
            )
        except OSError:
            # imminent_notified 마킹 실패는 다음 사이클 재시도 가능
            pass
        return

    if mode == "auto":
        result = refresh.fire(s, config)
        handler.handle_fire_result(s, result, config)
        return

    if mode == "hybrid":
        sid_short = (s.get("session_id") or s.get("sid_hash") or "")[:8]
        notifier.notify(
            f"💀 {sid_short} {config.refresh.hybrid_wait_seconds}s 내 입력 "
            "없으면 자동 갱신",
            terminal_bell=config.notify.terminal_bell,
            system_notification=config.notify.system_notification,
        )
        cancelled = sleep_with_cancel(
            float(config.refresh.hybrid_wait_seconds),
            sid_hash=s["sid_hash"],
            initial_user_input_at=s.get("last_user_input_at"),
        )
        if cancelled:
            log_info(f"[cancel] sid={s.get('sid_hash')} mode=hybrid")
            return
        fresh = load_state(s["sid_hash"])
        if fresh is None:
            return
        result = refresh.fire(fresh, config)
        handler.handle_fire_result(fresh, result, config)
        return


def sleep_with_cancel(
    seconds: float,
    *,
    sid_hash: str,
    initial_user_input_at,
) -> bool:
    """1초 단위 폴링으로 user input 감지.

    UserPromptSubmit hook이 ``last_user_input_at`` 갱신 → 그 변화 또는 세션 삭제
    감지 시 True (cancel). 끝까지 변화 없으면 False.

    ``initial_user_input_at`` 은 string ISO 또는 datetime/None 허용.
    """
    initial = (
        parse_iso(initial_user_input_at)
        if isinstance(initial_user_input_at, str)
        else initial_user_input_at
    )

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(1.0)
        fresh = load_state(sid_hash)
        if fresh is None:
            return True
        fresh_input = parse_iso(fresh.get("last_user_input_at"))
        if fresh_input is None:
            continue
        if initial is None or fresh_input > initial:
            return True
    return False

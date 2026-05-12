"""claude -p 헤드레스 호출 + FireReason 분기.

Phase 2a 범위: ``fire(state, config)`` 와 ``disable_session(s, ...)`` 만 제공.
실제 호출 결과를 받아 next_refresh_at / backoff 등 후처리 (``handle_fire_result``)
는 Phase 2b에서 추가된다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from daemon import notifier
from lib.logger import log_warn
from lib.state import update_state


class FireReason(str, Enum):
    OK = "ok"
    CACHE_COLD = "cache_cold"
    NETWORK_ERROR = "network_error"
    AUTH_ERROR = "auth_error"
    PROCESS_ERROR = "process_error"
    TIMEOUT = "timeout"
    BAD_OUTPUT = "bad_output"


TRANSIENT_REASONS: frozenset[FireReason] = frozenset({
    FireReason.NETWORK_ERROR,
    FireReason.TIMEOUT,
    FireReason.PROCESS_ERROR,
    FireReason.BAD_OUTPUT,
})

PERMANENT_REASONS: frozenset[FireReason] = frozenset({FireReason.AUTH_ERROR})

# stderr.lower() 매칭용 — 전부 lowercase.
# "forbidden" 단독은 HTTP 403 등에서 false positive 위험으로 제외 (인증 외 사유도
# 403을 쓰므로 영구 disable 트리거 부적합). 진짜 인증 실패는 다른 패턴이 잡고,
# 만약 누락돼도 PR 5의 5회 연속 실패 누적 disable이 backstop.
AUTH_ERROR_PATTERNS: tuple[str, ...] = (
    "authentication",
    "unauthorized",
    "login required",
    "credential",
    "api key",
    "expired token",
)

_RAW_STDOUT_LIMIT = 500


@dataclass
class FireResult:
    success: bool
    reason: FireReason
    cache_read: int = 0
    cache_create: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: Optional[str] = None
    raw_stdout: str = ""


def fire(state: dict, config) -> FireResult:
    """``claude -p`` 헤드레스 호출. usage 추출 후 FireReason 분기.

    cwd는 원본 세션 cwd로 실행 — credential / claude config 정합.
    """
    cmd = [
        "claude", "-p", config.refresh.prompt,
        "--resume", state["session_id"],
        "--fork-session",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.refresh.fire_timeout_seconds,
            cwd=state.get("cwd"),
        )
    except subprocess.TimeoutExpired:
        return FireResult(success=False, reason=FireReason.TIMEOUT)
    except (FileNotFoundError, PermissionError) as e:
        return FireResult(
            success=False,
            reason=FireReason.PROCESS_ERROR,
            raw_stdout=str(e)[:_RAW_STDOUT_LIMIT],
        )

    if proc.returncode != 0:
        stderr_lower = (proc.stderr or "").lower()
        if any(p in stderr_lower for p in AUTH_ERROR_PATTERNS):
            reason = FireReason.AUTH_ERROR
        else:
            reason = FireReason.NETWORK_ERROR
        return FireResult(
            success=False,
            reason=reason,
            raw_stdout=(proc.stderr or "")[:_RAW_STDOUT_LIMIT],
        )

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return FireResult(
            success=False,
            reason=FireReason.BAD_OUTPUT,
            raw_stdout=(proc.stdout or "")[:_RAW_STDOUT_LIMIT],
        )

    # JSON top-level이 object가 아니면 (list/숫자/문자열 등) 스키마 깨짐 → BAD_OUTPUT
    if not isinstance(data, dict):
        return FireResult(
            success=False,
            reason=FireReason.BAD_OUTPUT,
            raw_stdout=(proc.stdout or "")[:_RAW_STDOUT_LIMIT],
        )

    # usage 키가 mapping이 아닌 타입으로 오면 스키마 깨짐 → BAD_OUTPUT.
    # None / 누락은 빈 dict로 fallback (cache_read=0 → CACHE_COLD 흐름).
    usage = data.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        return FireResult(
            success=False,
            reason=FireReason.BAD_OUTPUT,
            raw_stdout=(proc.stdout or "")[:_RAW_STDOUT_LIMIT],
        )
    model_usage = data.get("modelUsage")
    model = (
        next(iter(model_usage.keys()), None)
        if isinstance(model_usage, dict)
        else None
    )

    result = FireResult(
        success=True,
        reason=FireReason.OK,
        cache_read=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_create=int(usage.get("cache_creation_input_tokens", 0) or 0),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        model=model,
    )
    # cache_read=0 → 캐시 이미 만료 (호출은 성공했지만 의미 없음)
    if result.cache_read == 0:
        result.success = False
        result.reason = FireReason.CACHE_COLD
    return result


def disable_session(
    s: dict,
    *,
    reason: str,
    message: str,
    notify: bool = True,
) -> None:
    """delete 대신 disabled 마커로 보존. /cn:status에서 원인 확인 가능.

    update_state OSError는 흡수 — daemon 중단 방지. 저장이 실패하면 알림도
    발사하지 않는다 (사용자가 disable 됐다고 오인하는 것을 막기 위함). 다음
    poll cycle에서 재시도된다.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    def _mut(x: dict) -> dict:
        return {
            **x,
            "disabled": True,
            "disabled_reason": reason,
            "disabled_at": now_iso,
            "next_refresh_at": None,
            "last_fire_at": None,
            "last_fire_reason": reason,
        }

    try:
        update_state(s["sid_hash"], _mut, allow_create=False)
    except OSError as e:
        log_warn(
            f"[refresh] disable_session update_state failed "
            f"sid={s.get('sid_hash')} err={e}"
        )
        return

    if notify:
        notifier.notify(message)

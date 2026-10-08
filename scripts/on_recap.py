#!/usr/bin/env python3
"""Stop hook 의 sync 본체 — turn 종료 시각을 marker.latest_fire 에 기록한다.

v0.11.0: 채팅에 띄우던 recap 박스(만료 시각·목숨·예산)는 없앴다. 같은 정보는
mod(hooks/register.tsx)가 프롬프트 위 카운트다운 띠 뒤에 붙인다. 출력 없음.

PRD 불변: 어떤 실패도 chat 동작 차단 X (silent fail).
"""
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.install_version import is_latest_install  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _read_hook_input() -> dict:
    """Stop hook stdin payload(JSON) 1회 read. 실패 시 빈 dict."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _resolve_session_id(payload: dict) -> str:
    sid = payload.get("session_id", "")
    if sid:
        return sid
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def _record_stop(sid_hash: str) -> None:
    """marker.latest_fire = 이번 Stop 시각 (ns). cn_status 다음 발동·active 판정과
    cn_set 의 timer 추정, refresh.py --now 의 사용자 활동 판정 기준.
    저장 실패는 silent.
    """
    marker = Marker.load(sid_hash)
    marker.latest_fire = time.time_ns()
    try:
        marker.save()
    except OSError as e:
        log_warn(f"[on_recap] marker save 실패: {type(e).__name__}: {e}")


def _main_impl() -> int:
    if not is_latest_install():
        return 0
    sid = _resolve_session_id(_read_hook_input())
    if not sid:
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0
    _record_stop(sid_hash)
    return 0


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())

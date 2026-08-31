#!/usr/bin/env python3
"""SessionStart hook — matcher "clear|compact" 전용 (v0.8.0).

/compact (수동·auto) 나 /clear 가 일어나면 marker 에 suppressed_at_ns 를 기록해
pending refresh.py 의 소생(wake ping / 알림) 을 억제한다. compact 는 컨텍스트를
재작성하므로 옛 cache 를 살려봐야 낭비다. 다음 진짜 user prompt 가 오면
on_user_prompt.py 가 last_user_activity_at_ns 를 갱신하면서 자동 해제된다.

stdout 출력 금지 — SessionStart hook 의 stdout 은 세션 컨텍스트에 주입된다.
PRD 불변: 어떤 실패도 chat 동작 차단 X.
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
from lib.logger import log_info, log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _load_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    if not is_latest_install():
        return 0
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id") or os.environ.get(
            "CLAUDE_CODE_SESSION_ID", ""
        )
        if not session_id:
            return 0
        try:
            sid_hash = sanitize(session_id)
            marker = Marker.load(sid_hash)
            marker.suppressed_at_ns = time.time_ns()
            marker.save()
            log_info(f"[session_start] 소생 억제 sid={sid_hash}")
        except (ValueError, OSError) as e:
            log_warn(f"[session_start] 억제 기록 실패: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        try:
            log_warn(f"[session_start] unexpected error: {type(e).__name__}: {e}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

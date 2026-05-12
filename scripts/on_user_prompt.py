#!/usr/bin/env python3
"""UserPromptSubmit hook 엔트리.

``last_user_input_at`` + ``current_turn_started_at`` 갱신.
``allow_create=False`` 이므로 Stop hook이 한 번도 발화 안 한 신규 세션은 추적 안 됨.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.logger import log_warn  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.state import update_state  # noqa: E402


def _load_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id", "")
        if not session_id:
            return 0

        sid_hash = sanitize(session_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        update_state(
            sid_hash,
            lambda x: {
                **x,
                "last_user_input_at": now_iso,
                "current_turn_started_at": now_iso,
            },
            allow_create=False,
        )
    except Exception as e:  # noqa: BLE001
        try:
            log_warn(f"[user_prompt] unexpected error: {type(e).__name__}: {e}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

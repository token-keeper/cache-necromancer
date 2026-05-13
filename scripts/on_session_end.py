#!/usr/bin/env python3
"""SessionEnd hook 엔트리.

세션 종료 시 state 파일 + lock 파일 정리 (per-session lock 안에서 안전하게).
``async: true`` 로 등록되어 Claude Code 종료를 차단하지 않는다.
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.logger import log_info, log_warn  # noqa: E402
from lib.plugin_state import is_plugin_active  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.state import delete_state  # noqa: E402


def _load_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    if not is_plugin_active():
        return 0
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id", "")
        if not session_id:
            return 0

        sid_hash = sanitize(session_id)
        delete_state(sid_hash)
        log_info(f"[session_end] sid={sid_hash}")
    except Exception as e:  # noqa: BLE001
        try:
            log_warn(f"[session_end] unexpected error: {type(e).__name__}: {e}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

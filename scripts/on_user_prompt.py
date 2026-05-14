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
from lib.plugin_state import is_plugin_active  # noqa: E402
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


def _make_prompt_excerpt(prompt: str, max_chars: int = 80) -> str | None:
    """사용자 자연어 prompt 의 첫 줄 + ``max_chars`` truncate.

    slash command (`/` 시작), 빈 텍스트는 skip. cn:status 박스에 표시될 마지막
    user prompt 발췌용. 환경변수 ``CN_TRACK_LAST_PROMPT=0`` 시 비활성.

    반환값이 ``None`` 이면 호출 측에서 state 의 기존 excerpt 를 그대로 보존 —
    slash command 호출이 직전 자연어 prompt 를 덮어쓰지 않게 하기 위한 의도적 동작.
    """
    if os.environ.get("CN_TRACK_LAST_PROMPT") == "0":
        return None
    if not prompt:
        return None
    stripped = prompt.strip()
    if not stripped or stripped.startswith("/"):
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return None
    if len(first_line) > max_chars:
        first_line = first_line[: max_chars - 3] + "..."
    return first_line


def main() -> int:
    if not is_plugin_active():
        return 0
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id", "")
        if not session_id:
            return 0

        sid_hash = sanitize(session_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        excerpt = _make_prompt_excerpt(stdin.get("prompt", ""))

        def _update(x: dict) -> dict:
            updated = {
                **x,
                "last_user_input_at": now_iso,
                "current_turn_started_at": now_iso,
            }
            if excerpt:
                updated["last_user_prompt_excerpt"] = excerpt
            return updated

        update_state(sid_hash, _update, allow_create=False)
    except Exception as e:  # noqa: BLE001
        try:
            log_warn(f"[user_prompt] unexpected error: {type(e).__name__}: {e}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

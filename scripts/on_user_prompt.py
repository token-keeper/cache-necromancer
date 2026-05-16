#!/usr/bin/env python3
"""UserPromptSubmit hook (TECH_SPEC §5).

사용자가 chat 에 input 시:
  1. marker.wake_count = 0 reset (max_refresh_count 는 "한 번 자리비움" 상한)
  2. marker.last_prompt = truncate(stdin payload 의 prompt, 40자)
     /cn:status 에서 다른 세션 식별용. PRD §8 예외 (single-user alpha 가정).

PRD 불변: 어떤 실패도 chat 동작 차단 X (best-effort, exit 0).
"""
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

PROMPT_MAX_CHARS = 40


def _load_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def _truncate_prompt(raw: str) -> str:
    """첫 줄만 + 40자 초과 시 '…' 표시 (control char 제거 + strip)."""
    if not raw:
        return ""
    first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
    # 보이지 않는 control char 제거 (tab/space 외)
    cleaned = "".join(c for c in first_line if c.isprintable() or c == " ")
    if len(cleaned) <= PROMPT_MAX_CHARS:
        return cleaned
    return cleaned[:PROMPT_MAX_CHARS].rstrip() + "…"


def main() -> int:
    try:
        # session_id 우선 stdin, fallback environment
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id") or os.environ.get(
            "CLAUDE_CODE_SESSION_ID", ""
        )
        if not session_id:
            return 0
        sid_hash = sanitize(session_id)
    except (ValueError, TypeError):
        return 0

    prompt_truncated = _truncate_prompt(str(stdin.get("prompt", "")))

    try:
        marker = Marker.load(sid_hash)
        marker.wake_count = 0
        if prompt_truncated:
            marker.last_prompt = prompt_truncated
        marker.save()
    except OSError as e:
        try:
            log_warn(f"[user_prompt] marker save 실패: {type(e).__name__}: {e}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

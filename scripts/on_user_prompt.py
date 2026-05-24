#!/usr/bin/env python3
"""UserPromptSubmit hook (TECH_SPEC §5).

사용자가 chat 에 input 시:
  1. marker.wake_count = 0 reset (max_refresh_count 는 "한 번 자리비움" 상한)
  2. marker.last_prompt = truncate(stdin payload 의 prompt, 40자)
     /cn:status 에서 다른 세션 식별용. PRD §8 예외 (single-user alpha 가정).

자기간섭 방지: refresh.py 의 PING 및 Claude Code 의 background
task-notification 도 user prompt 로 hook 에 도달함. system event 인
prompt 는 reset/last_prompt 갱신 skip — 진짜 user input 만 reset 한다.

판별 기준 (실제 stdin 형식 디버그 확인):
  - `<task-notification>` 으로 시작 → background event (PING wrapper 포함)
  - PING_PREFIX (`[cn:keepalive`) 가 prompt 안에 substring 으로 존재 → wrapped PING

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
# refresh.py 의 PING_PREFIX 와 동일 — 자기간섭 방지용 식별자.
# 둘 다 동시 변경 필요 (다음 lib 이동 시 통합 예정).
PING_PREFIX = "[cn:keepalive"


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


# macOS path 에 ANSI escape / 제어문자가 포함 가능 (`mkdir $'\x1b[31m...'`).
# /cn:status 박스 출력 교란 + terminal escape 주입 방지.
CWD_MAX_CHARS = 200


def _sanitize_cwd(raw: str) -> str:
    """첫 줄만 + control char 제거 + 200자 초과 시 '…' 표시."""
    if not raw:
        return ""
    first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
    cleaned = "".join(c for c in first_line if c.isprintable() or c == " ")
    if len(cleaned) <= CWD_MAX_CHARS:
        return cleaned
    return cleaned[:CWD_MAX_CHARS].rstrip() + "…"


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

    raw_prompt = str(stdin.get("prompt", ""))
    # 시스템 이벤트 (background task, PING 자기 주입) 는 사용자 input 아님 → skip.
    # 이게 없으면 매 wake 마다 wake_count 가 0 으로 reset 되어 "1/N" 무한 반복 +
    # max_refresh_count cap 무력화.
    #
    # 실제 stdin prompt 형식 (디버그 확인):
    #   - PING:  '<task-notification>...<system-reminder>...[cn:keepalive ...]...'
    #   - bg task done: '<task-notification>\n<task-id>...</task-notification>'
    #   - 진짜 user input: 사용자가 입력한 raw 텍스트
    #
    # substring 매칭의 false positive: 사용자가 일부러 '[cn:keepalive' 텍스트를
    # 메시지에 포함시키면 reset skip. 영향 = 자기 marker 의 wake_count 만,
    # max_refresh_count cap 으로 보호됨. single-user alpha 가정상 수용.
    if raw_prompt.startswith("<task-notification>") or PING_PREFIX in raw_prompt:
        return 0

    prompt_truncated = _truncate_prompt(raw_prompt)
    cwd_value = _sanitize_cwd(str(stdin.get("cwd", "")))

    try:
        marker = Marker.load(sid_hash)
        marker.wake_count = 0
        if prompt_truncated:
            marker.last_prompt = prompt_truncated
        if cwd_value:
            marker.cwd = cwd_value
        marker.save()
    except OSError as e:
        try:
            log_warn(f"[user_prompt] marker save 실패: {type(e).__name__}: {e}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

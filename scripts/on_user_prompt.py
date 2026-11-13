#!/usr/bin/env python3
"""UserPromptSubmit hook (TECH_SPEC §5).

사용자가 chat 에 input 시:
  1. marker.wake_count = 0 reset (auto_wakes 는 "한 번 자리비움" 상한).
     reset 전 wake_count > 0 이면 복귀 로그 1줄 (`[return] …`, 나중 통계용)
  2. marker.last_prompt = truncate(stdin payload 의 prompt, 40자)
     /cn:status 에서 다른 세션 식별용. PRD §8 예외 (single-user alpha 가정).
  3. cn: 메타 명령 (/cn:set·status·config 등) 은 activity 갱신 대상 아님 — 완전 skip.
  4. 복귀 판정: set_budget_total > 0 이고 충전 뒤 깨운 적이 있으면
     (last_wake_at_ns > set_charged_at_ns) /cn:set 덮어쓰기를 둘 다 0 으로 비운다.
  5. wake_off(/cn:set 0·off) 는 건드리지 않는다 — 세션 끝까지 유지.

자기간섭 방지: refresh.py 의 PING, background task-notification, 피어 세션·
팀메이트 메시지도 user prompt 로 hook 에 도달한다.
  - PING·/cn: 메타 명령: marker 를 건드리지 않고 return.
  - task-notification·피어/팀메이트 메시지: 사용자 활동은 아니지만 turn 은 시작된다 —
    last_turn_start_at_ns 만 기록 (refresh.py 의 진행 중 turn 판정). wake_count 리셋·
    activity·복귀 판정은 진짜 입력만.

판별 기준 (앞 공백 무시):
  - `_NON_USER_PREFIXES` 로 시작 → background event·피어/팀메이트 메시지
  - PING_PREFIX (`[cn:keepalive`) 가 prompt 안에 substring 으로 존재 → wrapped PING
  - `_META_COMMAND_PREFIXES` 로 시작 → cn: 메타 명령

PRD 불변: 어떤 실패도 chat 동작 차단 X (best-effort, exit 0).
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

PROMPT_MAX_CHARS = 40
# refresh.py 의 PING_PREFIX 와 동일 — 자기간섭 방지용 식별자.
# 둘 다 동시 변경 필요 (다음 lib 이동 시 통합 예정).
PING_PREFIX = "[cn:keepalive"

# cn: 메타 명령 (/cn:set·status·config) 은 "자리로 돌아옴" 신호가 아니다.
# activity 갱신·복귀 판정에서 제외 — 제외하지 않으면 set 직후 pending refresh 가
# supersede 되어 충전된 예산을 소비할 timer 가 사라진다 (spec §6, codex F1).
_META_COMMAND_PREFIXES = ("/cn:", "/cache-necromancer:cn:")

# 사용자가 친 게 아닌 prompt — 백그라운드 작업 완료·다른 세션·팀메이트 메시지
_NON_USER_PREFIXES = ("<task-notification>", "<cross-session-message", "<teammate-message")


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
    if not is_latest_install():
        return 0
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
    # 시스템 이벤트·피어 메시지·PING 자기 주입은 사용자 input 아님 → skip.
    # 이게 없으면 매 깨우기마다 wake_count 가 0 으로 reset 되어 auto_wakes 상한 무력화.
    #
    # substring 매칭의 false positive: 사용자가 일부러 '[cn:keepalive' 텍스트를
    # 메시지에 포함시키면 reset skip. 영향 = 자기 marker 의 wake_count 만.
    stripped = raw_prompt.lstrip()
    if PING_PREFIX in raw_prompt or stripped.startswith(_META_COMMAND_PREFIXES):
        return 0
    is_user = not stripped.startswith(_NON_USER_PREFIXES)

    prompt_truncated = _truncate_prompt(raw_prompt)
    cwd_value = _sanitize_cwd(str(stdin.get("cwd", "")))

    try:
        marker = Marker.load(sid_hash)
        now_ns = time.time_ns()
        # turn 시작 — 사용자 입력이 아니어도 기록 (진행 중 turn 에 ping 이 끼지 않게)
        marker.last_turn_start_at_ns = now_ns
        if not is_user:
            marker.save()
            return 0
        if marker.wake_count > 0:
            since = int(time.time()) - marker.last_wake_at
            log_info(
                f"[return] sid={sid_hash} wakes={marker.wake_count} since_last_wake_s={since}"
            )
        marker.wake_count = 0
        # 진짜 입력 시각 — refresh.py 가 마지막 Stop 과 비교해 진행 중 turn·복귀를 거른다
        marker.last_user_activity_at_ns = now_ns
        # 복귀 판정: 충전 뒤 깨운 적이 있으면 덮어쓰기 해제.
        # 충전 직후 아직 깨우기 없으면 (떠나기 전) 유지 — "하나만 더" 함정 방지.
        if (marker.set_budget_total > 0
                and marker.last_wake_at_ns > marker.set_charged_at_ns):
            marker.set_budget_remaining = 0
            marker.set_budget_total = 0
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

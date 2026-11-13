#!/usr/bin/env python3
"""캐시 깨우기 판정 + ping (v0.12.0).

mod(hooks/register.tsx)가 캐시 마지막 적중 시각(base) + refresh_interval_minutes 에
`refresh.py --now` 로 실행하고, exit 2 면 stderr ping 을 prompt 로 제출한다.
플래그 없이 불려도 같은 경로다 (sleep 없음).

판정 (lib/wake_plan.py 공통 규칙):
  1. 활성 설치본이 아니면 skip (로그 1줄)
  2. latest_fire == 0 → skip (세션 종료·Stop 없음)
  3. max(activity, turn_start) > latest_fire → skip (진행 중 turn·이미 돌아옴)
  4. suppressed_at_ns > max(activity, latest_fire) → skip (clear/compact 뒤 Stop 없음)
  5. remaining_wakes == 0 → skip (off / budget used / auto_wakes 도달)
  6. wake_count += 1 (덮어쓰기면 남은 수 −1) 저장 → 저장 실패면 ping 없이 0
  7. stderr ping + exit 2

PRD 불변: 어떤 실패도 chat 동작 차단 X (best-effort).
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import Config, ensure_config_file, load_config  # noqa: E402
from lib.install_version import is_latest_install  # noqa: E402
from lib.logger import log_info, log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.wake_plan import remaining_wakes, wake_mode  # noqa: E402

PING_PREFIX = "[cn:keepalive"


def _build_ping(nm: str) -> str:
    """동적 PING 메시지 — local 시각 + 'k/N' 카운트 포함.

    응답 형식도 'ok @HH:MM (k/N)' 으로 강제해서 chat history 만 봐도
    언제 몇 번째 깨우기였는지 확인 가능.
    """
    hhmm = datetime.now().strftime("%H:%M")
    return (
        f"{PING_PREFIX} {hhmm}, {nm}] "
        f"reply with exactly 'ok @{hhmm} ({nm})'. "
        "No tools, no analysis. Use minimal output tokens."
    )


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _read_payload() -> dict:
    """stdin JSON 1회 read. 비었거나 깨졌으면 빈 dict."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _resolve_session_id(payload: dict) -> str:
    """stdin JSON ({"session_id": ...}) 우선, env fallback."""
    sid = payload.get("session_id", "")
    if sid:
        return sid
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def _skip_reason(marker: Marker, config: Config) -> str:
    """remaining_wakes == 0 인 이유 — 로그용."""
    mode = wake_mode(marker)
    if mode == "off":
        return "off"
    if mode == "set":
        return "budget used"
    return f"auto_wakes {config.auto_wakes} 도달"


def _do_wake(marker: Marker, sid_hash: str, config: Config) -> int:
    """wake_count·덮어쓰기 남은 수 갱신 + 저장 후 stderr ping + exit 2.

    저장에 실패하면 ping 없이 0 — 상한이 캐시 유지보다 우선 (fail-closed).
    """
    if wake_mode(marker) == "set":
        consumed = marker.set_budget_total - marker.set_budget_remaining + 1
        marker.set_budget_remaining -= 1
        nm = f"{consumed}/{marker.set_budget_total}"
    else:
        nm = f"{marker.wake_count + 1}/{config.auto_wakes}"
    marker.wake_count += 1
    marker.last_wake_at_ns = time.time_ns()
    marker.last_wake_at = marker.last_wake_at_ns // 1_000_000_000
    try:
        marker.save()
    except OSError as e:
        log_warn(f"[refresh] marker save 실패, 깨우기 취소 sid={sid_hash}: {type(e).__name__}: {e}")
        return 0
    log_info(f"[refresh] wake sid={sid_hash} count={marker.wake_count} nm={nm}")
    print(_build_ping(nm), file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    # argv(--now)는 호환용으로 받기만 한다 — 경로는 하나
    if not is_latest_install():
        log_info("[refresh] 비활성 설치본, skip")
        return 0
    sid = _resolve_session_id(_read_payload())
    if not sid:
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0

    config_path = _resolve_root() / "config.toml"
    try:
        ensure_config_file(config_path)
    except OSError as e:
        log_warn(f"[refresh] config.toml 자동 생성 실패: {e}")
    config = load_config(config_path)
    marker = Marker.load(sid_hash)

    # SessionEnd 가 marker 를 지웠거나 Stop 기록이 없다 — 좀비 깨우기·marker 재생성 방지
    if marker.latest_fire == 0:
        log_info(f"[refresh] Stop 기록 없음 (세션 종료), skip sid={sid_hash}")
        return 0
    # 마지막 Stop 뒤 turn 시작(진짜 입력·task-notification·팀메이트 메시지) =
    # turn 진행 중(권한 대기·긴 도구 포함)이거나 이미 돌아옴
    if max(marker.last_user_activity_at_ns, marker.last_turn_start_at_ns) > marker.latest_fire:
        log_info(f"[refresh] Stop 뒤 turn 시작 있음, skip sid={sid_hash}")
        return 0
    # clear/compact 뒤 Stop 도 입력도 없으면 옛 캐시 — 살려도 낭비.
    # 압축 뒤 turn 이 Stop 까지 갔으면 새 캐시이므로 깨운다.
    if marker.suppressed_at_ns > max(marker.last_user_activity_at_ns, marker.latest_fire):
        log_info(f"[refresh] suppressed (clear/compact 뒤 Stop 없음), skip sid={sid_hash}")
        return 0
    if remaining_wakes(marker, config) == 0:
        log_info(f"[refresh] {_skip_reason(marker, config)}, skip sid={sid_hash}")
        return 0

    return _do_wake(marker, sid_hash, config)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

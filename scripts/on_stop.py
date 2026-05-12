#!/usr/bin/env python3
"""Stop hook 엔트리.

Claude Code의 ``Stop`` hook이 호출. stdin으로 JSON을 받아:
1. session_id sanitize → sid_hash
2. state 파일 update (allow_create=True, default_state factory)
3. 데몬 lazy spawn

실패는 silent — caller는 항상 exit 0 (PRD 불변).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 패키지 경로 보장
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from daemon.transcript import extract_last_turn_usage  # noqa: E402
from lib.config import load_config  # noqa: E402
from lib.logger import log_info, log_user_turn, log_warn  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.state import default_state, parse_iso, update_state  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def _load_stdin_json() -> dict:
    """stdin에서 JSON 읽기. 실패 시 빈 dict."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def _build_stop_mutator(stdin: dict, now: datetime, config) -> tuple[callable, str, dict]:
    """mutator + sid_hash + capture(prev_turn_start/prev_last_fire) 반환.

    log_user_turn은 update_state lock 밖에서 호출하기 위해 mutator 내부에서는
    state 의 prev 값들만 capture dict 에 저장한다 (lock holding time 최소화).
    """
    session_id = stdin.get("session_id", "")
    sid_hash = sanitize(session_id) if session_id else None
    transcript_path = stdin.get("transcript_path", "")
    cwd = stdin.get("cwd", "")
    capture: dict = {}

    def mutator(x: dict) -> dict:
        # 빈 dict면 default_state로 base 채움 (CRITICAL fix)
        if not x:
            x = default_state(
                session_id=session_id,
                sid_hash=sid_hash or "unknown",
                transcript_path=transcript_path,
                cwd=cwd,
                now=now,
            )

        # lock 밖에서 after_fire 판정 / log_user_turn 호출하기 위해 capture
        capture["prev_turn_start"] = x.get("current_turn_started_at")
        capture["prev_last_fire"] = x.get("last_fire_at")

        return {
            **x,
            "session_id": session_id,
            "sid_hash": sid_hash,
            "transcript_path": transcript_path,
            "cwd": cwd,
            "last_stop_at": now.isoformat(),
            "next_refresh_at": (
                now + timedelta(minutes=config.refresh_interval_minutes)
            ).isoformat(),
            "imminent_notified": False,
            "current_turn_started_at": None,  # turn 종료
            "cache_cold_retries": 0,  # 사용자 활동 = 새 사이클
            # last_fire_at은 건드리지 않음 (after_fire 판정용)
        }

    return mutator, sid_hash, capture


def _maybe_log_user_turn(
    sid_hash: str,
    session_id: str,
    transcript_path: str,
    capture: dict,
    now: datetime,
) -> None:
    """update_state lock 해제 후 호출 — transcript IO + log IO 가 lock 밖에서 발생."""
    if not (sid_hash and capture.get("prev_turn_start")):
        return
    usage = extract_last_turn_usage(
        Path(transcript_path) if transcript_path else None
    )
    if not usage:
        return

    prev_turn_start = capture.get("prev_turn_start")
    prev_last_fire = capture.get("prev_last_fire")
    after_fire = False
    if prev_turn_start and prev_last_fire:
        try:
            tstart = parse_iso(prev_turn_start)
            tfire = parse_iso(prev_last_fire)
            if tstart and tfire:
                after_fire = tfire < tstart
        except (ValueError, TypeError):
            after_fire = False

    try:
        log_user_turn(
            sid_hash=sid_hash,
            session_id=session_id,
            usage=usage,
            after_fire=after_fire,
            now=now,
        )
    except OSError:
        pass


def main() -> int:
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id", "")
        if not session_id:
            return 0  # session_id 없으면 silent

        now = datetime.now(timezone.utc)
        root = _resolve_root()
        config = load_config(root / "config.toml")

        mutator, sid_hash, capture = _build_stop_mutator(stdin, now, config)
        if sid_hash is None:
            return 0

        update_state(sid_hash, mutator, allow_create=True)
        log_info(f"[stop] sid={sid_hash}")

        # lock 밖에서 transcript IO + user_turn log
        _maybe_log_user_turn(
            sid_hash=sid_hash,
            session_id=session_id,
            transcript_path=stdin.get("transcript_path", ""),
            capture=capture,
            now=now,
        )

        # 데몬 lazy spawn
        from daemon.spawn import spawn_daemon_if_needed
        spawn_daemon_if_needed()
    except Exception as e:  # noqa: BLE001
        # PRD 불변: hook은 어떤 경우에도 Claude Code에 영향 주지 않는다
        try:
            log_warn(f"[stop] unexpected error: {type(e).__name__}: {e}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

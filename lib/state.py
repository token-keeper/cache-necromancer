"""세션별 state 파일 관리 (atomic write + per-session flock + factory)."""
import fcntl
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Callable, Optional


def _resolve_state_dir() -> Path:
    """CN_ROOT 환경변수가 있으면 그 하위 state/, 없으면 ~/.cache-necromancer/state/."""
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root) / "state"
    return Path.home() / ".cache-necromancer" / "state"


STATE_DIR: Path = _resolve_state_dir()
STATE_LOCK_DEADLINE: float = 4.0


class StateLockTimeout(Exception):
    """state lock을 deadline 안에 획득하지 못함."""


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    """ISO 8601 문자열 → datetime. None 또는 빈 값은 None."""
    if not s:
        return None
    return datetime.fromisoformat(s)


def default_state(
    session_id: str,
    sid_hash: str,
    transcript_path: str,
    cwd: str,
    now: datetime,
) -> dict:
    """모든 필수 필드를 안전한 기본값으로 채운 신규 state."""
    return {
        "session_id": session_id,
        "sid_hash": sid_hash,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "last_stop_at": None,
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
        "refresh_count": 0,
        "next_refresh_at": None,
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": now.isoformat(),
    }


def acquire_state_lock_with_timeout(
    lock_path: Path,
    timeout: float = STATE_LOCK_DEADLINE,
) -> IO:
    """non-blocking flock + deadline retry (10ms 간격).

    Raises:
        StateLockTimeout: deadline 안에 락을 못 잡은 경우.
    """
    deadline = time.monotonic() + timeout
    f = open(lock_path, "a+")
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.monotonic() >= deadline:
                f.close()
                raise StateLockTimeout(
                    f"lock contention >{timeout}s: {lock_path}"
                )
            time.sleep(0.01)


def update_state(
    sid_hash: str,
    mutator: Callable[[dict], Optional[dict]],
    *,
    allow_create: bool = False,
) -> None:
    """state 파일을 atomic하게 update.

    Args:
        sid_hash: sanitize된 session id.
        mutator: 현재 state dict를 받아 새 state를 반환. None 반환 시 write 생략.
        allow_create: True면 파일이 없을 때 새로 만듦.
            False (daemon-origin 호출용)는 파일이 없으면 silent return —
            SessionEnd 삭제 직후 stale write로 재생성되는 race를 차단한다.

    Lock timeout 시 silent return. caller가 log를 결정한다.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return
    try:
        if not path.exists():
            if not allow_create:
                return
            data: dict = {}
        else:
            data = json.loads(path.read_text())
        result = mutator(data)
        if result is None:
            return
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(result, indent=2))
        os.replace(tmp, path)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def delete_state(sid_hash: str) -> None:
    """state 파일을 per-session lock 획득 후 삭제.

    SessionEnd hook과 poller GC가 호출한다.
    """
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return
    try:
        if path.exists():
            path.unlink()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def load_state(sid_hash: str) -> Optional[dict]:
    """state 파일을 읽는다. 없으면 None."""
    path = STATE_DIR / f"{sid_hash}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_all_states() -> list[dict]:
    """STATE_DIR의 모든 state JSON을 읽는다. corrupt 파일은 skip."""
    if not STATE_DIR.exists():
        return []
    out: list[dict] = []
    for p in STATE_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out

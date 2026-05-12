"""세션별 state 파일 관리 (atomic write + per-session flock + factory).

보안 / 안전 정책:
- state dir은 0700, state JSON은 0600 권한 (session_id / transcript_path / cwd 보호).
- corrupt JSON은 ``.corrupt.{timestamp}`` 로 백업 후 새 데이터로 진행.
- orphan ``.lock`` 파일은 ``delete_state`` 가 정리.
- ``allow_create=False`` + 파일 부재면 lock 파일도 안 만든다 (silent return).
"""
import fcntl
import json
import os
import time
from datetime import datetime, timezone
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

    Lock 파일은 0600 권한으로 생성. ``os.open`` 으로 mode 인자 명시해
    umask 의존을 제거한다.

    Raises:
        StateLockTimeout: deadline 안에 락을 못 잡은 경우.
    """
    deadline = time.monotonic() + timeout
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    f = os.fdopen(fd, "a+")
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


def _ensure_state_dir() -> None:
    """STATE_DIR을 0700 권한으로 보장 (이미 있으면 권한 강제 적용)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass  # 권한 변경 실패해도 진행 (best effort)


def _quarantine_corrupt(path: Path) -> None:
    """손상된 state 파일을 ``.corrupt.{timestamp}`` 로 옮긴다."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup = path.with_name(f"{path.stem}.corrupt.{ts}")
    try:
        path.rename(backup)
    except OSError:
        pass  # 백업 실패해도 caller가 새 데이터로 진행 가능하도록


def _atomic_write_state(path: Path, data: dict) -> None:
    """tmp 파일 → 0600 권한 강제 → os.replace로 atomic rename.

    stale tmp 파일이 이미 존재해도 ``os.fchmod`` 로 0600 보장.
    fdopen 실패 시 raw fd close + tmp 삭제로 자원 누수 차단.
    """
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.fchmod(fd, 0o600)  # stale tmp가 더 관대한 권한이어도 강제 적용
    except OSError:
        pass
    try:
        f = os.fdopen(fd, "w")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp.unlink(missing_ok=True)
        raise
    try:
        with f:
            json.dump(data, f, indent=2)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


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

    동작:
    - Lock timeout 시 silent return.
    - corrupt JSON 만나면 ``.corrupt.{ts}`` 로 백업 후 빈 dict로 시작.
    - ``allow_create=False`` + 파일 부재면 lock 파일도 안 만든다 (조기 return).
    """
    path = STATE_DIR / f"{sid_hash}.json"
    # CRITICAL fix: allow_create=False 경로에서 lock 파일을 만들지 않는다.
    if not allow_create and not path.exists():
        return
    _ensure_state_dir()
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return
    try:
        # 락 획득 후 다시 한 번 존재 확인 (race 가능)
        if not path.exists():
            if not allow_create:
                return
            data: dict = {}
        else:
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                _quarantine_corrupt(path)
                if not allow_create:
                    return
                data = {}
        result = mutator(data)
        if result is None:
            return
        _atomic_write_state(path, result)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def delete_state(sid_hash: str) -> None:
    """state 파일 + lock 파일을 per-session lock 획득 후 정리.

    SessionEnd hook과 poller GC가 호출한다. orphan ``.lock`` 누수 방지.

    Race window 명시: 락 보유 중에 lock_path를 unlink한다. POSIX에서는
    이미 열린 fd는 anonymous inode로 유지되어 락이 계속 유효. 다른
    프로세스가 unlink 후 close 사이에 같은 이름의 새 파일을 만들면 다른
    inode를 잡지만, state json은 이미 삭제됐으므로 그 프로세스의
    ``update_state(allow_create=False)`` 는 조기 return → 무해.
    """
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    if not lock_path.exists() and not path.exists():
        return  # 정리할 게 없음
    _ensure_state_dir()
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return
    try:
        path.unlink(missing_ok=True)
        # 락 보유 중 lock 파일 unlink (anonymous inode로 유지)
        lock_path.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def load_state(sid_hash: str) -> Optional[dict]:
    """state 파일을 읽는다. 없거나 corrupt면 None."""
    path = STATE_DIR / f"{sid_hash}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_all_states() -> list[dict]:
    """STATE_DIR의 모든 state JSON을 읽는다. corrupt 파일은 skip."""
    if not STATE_DIR.exists():
        return []
    out: list[dict] = []
    for p in STATE_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out

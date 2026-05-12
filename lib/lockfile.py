"""데몬 단일 인스턴스 보장 (lockfile + PID + start_time).

PID 재사용으로 인한 오인을 방지하기 위해 PID와 함께 ``ps -o lstart=``
출력(프로세스 시작 시각)을 기록한다. liveness 체크 시 둘 다 일치해야 alive.

부모 디렉토리는 0700 권한, lock 파일은 0600 권한으로 보장된다.
"""
import fcntl
import json
import os
import subprocess
from pathlib import Path
from typing import IO, Optional


def proc_start_time(pid: int) -> Optional[str]:
    """``ps -o lstart= -p PID`` 출력. 죽은 프로세스 / ps 미설치 / timeout이면 None.

    macOS / linux 모두 호환. subprocess hang에 대비해 2초 timeout 적용.
    """
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        return out or None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return None


def is_daemon_alive(lock_path: Path) -> bool:
    """lockfile 내용(JSON: {pid, started}) + 현재 PID start_time이 일치해야 alive."""
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        return False
    try:
        meta = json.loads(lock_path.read_text())
        pid = int(meta["pid"])
        started = meta["started"]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return False
    current = proc_start_time(pid)
    return current is not None and current == started


def acquire_daemon_lock(lock_path: Path) -> Optional[IO]:
    """단일 데몬 보장. 다른 데몬이 alive면 None, stale은 강제 회수.

    'a+' 모드로 열어 lock 획득 전 파일 truncate를 막는다.
    획득 성공 후에만 ``seek(0) + truncate() + write({pid, started})``.
    호출자는 caller가 파일 디스크립터를 닫지 않고 데몬 생애 동안 유지해야 한다.

    lock 파일이 들어갈 부모 디렉토리를 0700 권한으로 보장한다.
    """
    # 부모 디렉토리 보장 (daemon 첫 실행 시 ~/.cache-necromancer/ 미존재 가능)
    parent = lock_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent, 0o700)
    except OSError:
        pass
    f = open(lock_path, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        if is_daemon_alive(lock_path):
            return None
        # stale → 재시도
        f = open(lock_path, "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None

    # 락 획득 후 PID + start_time 기록
    f.seek(0)
    f.truncate()
    pid = os.getpid()
    f.write(json.dumps({"pid": pid, "started": proc_start_time(pid)}))
    f.flush()
    try:
        os.chmod(lock_path, 0o600)
    except OSError:
        pass
    return f

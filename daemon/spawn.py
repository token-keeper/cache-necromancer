"""데몬 lazy spawn 헬퍼.

Stop hook이 호출. lockfile로 alive 체크 후 죽었으면 백그라운드로 ``python -m daemon`` 실행.
"""
import os
import subprocess
import sys
from pathlib import Path

from lib.lockfile import is_daemon_alive


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def _project_root() -> Path:
    """daemon 패키지가 있는 상위 디렉토리."""
    return Path(__file__).resolve().parent.parent


def spawn_daemon_if_needed() -> None:
    """데몬이 살아있지 않으면 백그라운드 spawn. 실패는 silent."""
    lock_path = _resolve_root() / "daemon.lock"
    if is_daemon_alive(lock_path):
        return

    try:
        subprocess.Popen(
            [sys.executable, "-m", "daemon"],
            cwd=str(_project_root()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=os.environ.copy(),
        )
    except (OSError, FileNotFoundError):
        pass  # silent (PRD 불변: hook 실패가 Claude Code 영향 없음)

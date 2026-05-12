"""cache-necromancer 데몬 진입점.

``python -m daemon`` 으로 실행. lockfile로 단일 인스턴스 보장.
"""
import os
import sys
from pathlib import Path

from lib.config import load_config
from lib.lockfile import acquire_daemon_lock
from lib.logger import log_info, log_warn

from daemon.poller import run_poll_loop


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def main() -> int:
    root = _resolve_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass

    config_path = root / "config.toml"
    config = load_config(config_path)

    lock_path = root / "daemon.lock"
    lock_f = acquire_daemon_lock(lock_path)
    if lock_f is None:
        log_info("[daemon] another daemon alive, exit")
        return 0

    try:
        run_poll_loop(config)
    except KeyboardInterrupt:
        log_info("[daemon] interrupted, shutting down")
    except Exception as e:
        log_warn(f"[daemon] unexpected error: {type(e).__name__}: {e}")
        return 1
    finally:
        try:
            lock_f.close()
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

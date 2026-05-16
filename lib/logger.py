"""일자별 회전 로그.

- ``cn.log.YYYY-MM-DD``: info/warn (refresh.py / on_user_prompt / on_session_end).

민감정보(프롬프트 내용, 응답 본문, cwd, 절대경로) 절대 기록 안 함.
sid_hash와 토큰 수만 기록.

파일 권한 0600, 디렉토리 0700 (다른 로컬 사용자가 읽지 못하도록).
``OSError`` 는 silent 처리 (logger 실패가 caller crash를 일으키지 않도록).

7일 후 자동 삭제는 사용자 수동 (README 안내).
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path


def _resolve_log_dir() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


LOG_DIR: Path = _resolve_log_dir()


def _today_suffix() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(filename_prefix: str, line: str) -> None:
    """일자별 파일에 line을 append. 파일 권한 0600, 디렉토리 0700.

    logger는 부수 기능이므로 OSError가 caller crash를 일으키면 안 된다.
    실패 시 silent (PRD 불변 조건: hook 실패가 Claude Code에 영향 없음).
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(LOG_DIR, 0o700)
        except OSError:
            pass
        path = LOG_DIR / f"{filename_prefix}.{_today_suffix()}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        try:
            with os.fdopen(fd, "a") as f:
                f.write(line + "\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    except OSError:
        pass  # silent fail (PRD 불변)


def log_info(msg: str) -> None:
    _append("cn.log", f"{_now_iso()} INFO  {msg}")


def log_warn(msg: str) -> None:
    _append("cn.log", f"{_now_iso()} WARN  {msg}")

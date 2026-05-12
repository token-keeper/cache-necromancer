"""일자별 회전 로그.

- ``daemon.log.YYYY-MM-DD``: 일반 info/warn.
- ``fire.log.YYYY-MM-DD``: fire 결과 raw data (Phase 4 대시보드용).
- ``user_turn.log.YYYY-MM-DD``: 사용자 turn usage + after_fire 판정.

민감정보(프롬프트 내용, 응답 본문, cwd, 절대경로) 절대 기록 안 함.
sid_hash와 토큰 수만 기록.

7일 후 자동 삭제는 Phase 4로 미룸 (v1은 사용자가 README 안내대로 수동 삭제 OK).
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


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
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{filename_prefix}.{_today_suffix()}"
    with open(path, "a") as f:
        f.write(line + "\n")


def log_info(msg: str) -> None:
    _append("daemon.log", f"{_now_iso()} INFO  {msg}")


def log_warn(msg: str) -> None:
    _append("daemon.log", f"{_now_iso()} WARN  {msg}")


def log_fire(
    sid_hash: str,
    session_id: Optional[str],
    model: Optional[str],
    reason: str,
    cache_read: int,
    cache_create: int,
    input_tokens: int,
    output_tokens: int,
    now: datetime,
) -> None:
    """fire 결과 raw log.

    민감정보 미기록: sid_hash + 토큰 수 + model + reason만.
    """
    line = (
        f"{now.isoformat()} | fire | sid={sid_hash} | model={model} | "
        f"reason={reason} | cache_read={cache_read} | "
        f"cache_create={cache_create} | input={input_tokens} | "
        f"output={output_tokens}"
    )
    _append("fire.log", line)


def log_user_turn(
    sid_hash: str,
    session_id: Optional[str],
    usage: dict,
    after_fire: bool,
    now: datetime,
) -> None:
    """사용자 turn 응답의 usage 기록.

    Phase 4 대시보드가 ``after_fire=true`` 비율로 Net saved 추정.
    """
    line = (
        f"{now.isoformat()} | user_turn | sid={sid_hash} | "
        f"model={usage.get('model', 'unknown')} | "
        f"cache_read={usage.get('cache_read_input_tokens', 0)} | "
        f"cache_create={usage.get('cache_creation_input_tokens', 0)} | "
        f"input={usage.get('input_tokens', 0)} | "
        f"output={usage.get('output_tokens', 0)} | "
        f"after_fire={'true' if after_fire else 'false'}"
    )
    _append("user_turn.log", line)

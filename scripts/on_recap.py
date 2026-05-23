#!/usr/bin/env python3
"""Stop hook 의 sync 본체 — recap 영역에 다음 wake 시각 표시.

design spec: docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md
PRD 불변: 어떤 실패도 chat 동작 차단 X (silent fail).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import ensure_config_file, load_config  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

_KST = timezone(timedelta(hours=9))


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _resolve_session_id() -> str:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            sid = data.get("session_id", "")
            if sid:
                return sid
    except (json.JSONDecodeError, OSError):
        pass
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def _main_impl() -> int:
    sid = _resolve_session_id()
    if not sid:
        return 0
    sanitize(sid)  # 다음 task 에서 실제 사용
    return 0


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] 예외 silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())

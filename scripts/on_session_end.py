#!/usr/bin/env python3
"""SessionEnd hook (TECH_SPEC §6).

세션 종료 시:
  1. 현재 sid 의 marker file 삭제
  2. marker_dir 전체 glob → 7일 초과 stale file 정리

``async: true`` 로 등록되어 Claude Code 종료를 차단하지 않는다.
PRD 불변: 어떤 실패도 chat 동작 차단 X.
"""
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.logger import log_info, log_warn  # noqa: E402
from lib.marker import Marker, cleanup_stale  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _load_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    try:
        stdin = _load_stdin_json()
        session_id = stdin.get("session_id") or os.environ.get(
            "CLAUDE_CODE_SESSION_ID", ""
        )
        if session_id:
            try:
                sid_hash = sanitize(session_id)
                Marker(sid_hash=sid_hash).delete()
                log_info(f"[session_end] marker 삭제 sid={sid_hash}")
            except (ValueError, OSError) as e:
                log_warn(f"[session_end] marker 삭제 실패: {type(e).__name__}: {e}")

        # 7일 초과 stale 정리 (다른 세션이 SessionEnd 못 받고 죽은 경우 보호)
        try:
            deleted = cleanup_stale()
            if deleted > 0:
                log_info(f"[session_end] stale marker 정리: {deleted}개")
        except OSError as e:
            log_warn(f"[session_end] stale cleanup 실패: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        try:
            log_warn(f"[session_end] unexpected error: {type(e).__name__}: {e}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

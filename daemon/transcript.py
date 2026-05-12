"""transcript JSONL 마지막 turn usage 추출 — Stop hook 100ms 보장.

파일 끝에서 ``TAIL_BYTES`` (기본 64KB) 만 읽고, 그 안에서 역방향으로 가장 최근
``type=assistant`` (또는 ``role=assistant``) 항목의 ``usage`` 를 반환. 못 찾으면
None (graceful degradation — 그 turn 의 user_turn log는 누락되지만 hook은 안전).

전체 transcript 파싱은 비동기 daemon job 영역 (Phase 4 대시보드).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

TAIL_BYTES: int = 64 * 1024
MAX_REVERSE_LINES: int = 200


def _read_tail(path: Path, max_bytes: int) -> str:
    """파일 끝에서 ``max_bytes`` 만 읽음. UTF-8 boundary 안전.

    파일이 max_bytes 보다 작으면 전체 읽음. 잘린 첫 줄은 버려 multi-byte
    boundary 깨짐을 회피.
    """
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        offset = max(0, size - max_bytes)
        f.seek(offset)
        chunk = f.read()

    if offset > 0:
        idx = chunk.find(b"\n")
        if idx >= 0:
            chunk = chunk[idx + 1:]

    return chunk.decode("utf-8", errors="replace")


def extract_last_turn_usage(transcript_path: Optional[Path]) -> Optional[dict]:
    """가장 최근 assistant turn 의 ``usage`` dict 반환.

    실패 (파일 없음 / 읽기 권한 / 파싱 실패 / assistant 없음 / usage 없음) 시
    None. Stop hook 안전 보장 — 절대 예외 던지지 않음.
    """
    if transcript_path is None:
        return None
    path = transcript_path if isinstance(transcript_path, Path) else Path(transcript_path)
    if not path.exists():
        return None

    try:
        tail = _read_tail(path, TAIL_BYTES)
    except (OSError, PermissionError):
        return None

    lines = tail.splitlines()[-MAX_REVERSE_LINES:]
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type") or entry.get("role")
        if entry_type != "assistant":
            continue
        message = entry.get("message")
        usage = None
        if isinstance(message, dict):
            usage = message.get("usage")
        if usage is None:
            usage = entry.get("usage")
        if isinstance(usage, dict) and usage:
            return usage
    return None

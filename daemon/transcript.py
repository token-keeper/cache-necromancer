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
        # **첫 assistant entry에서 결정** — 더 이전 entry로 fallback 금지.
        # 그 안에 usage가 없으면 이번 turn은 usage 미상이므로 None 반환
        # (이전 turn의 usage를 잘못 사용해 user_turn log를 오염시키는 결함 차단).
        message = entry.get("message")
        usage = None
        if isinstance(message, dict):
            usage = message.get("usage")
        if usage is None:
            usage = entry.get("usage")
        if isinstance(usage, dict) and usage:
            return usage
        return None
    return None


def extract_last_assistant_model(transcript_path: Optional[Path]) -> Optional[str]:
    """가장 최근 assistant turn 의 ``model`` 이름 반환.

    fire 호출 시 ``--model`` 로 명시해 사용자 chat 과 같은 prompt cache 에
    write/hit 하기 위함. Anthropic prompt cache 는 model 별로 분리되므로
    fire 가 사용자 chat 과 다른 model 로 호출되면 cache miss 가 일어난다.

    실패 (파일 없음 / 읽기 권한 / 파싱 실패 / assistant 없음 / model 없음) 시
    None — 호출자가 ``--model`` 명시 없이 CLI default 로 fallback.
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
        # 첫 assistant entry 에서 결정 — 더 이전 entry 로 fallback 금지
        # (모델 바뀐 turn 직후의 fire 가 이전 모델로 가는 결함 차단).
        message = entry.get("message")
        model = None
        if isinstance(message, dict):
            model = message.get("model")
        if model is None:
            model = entry.get("model")
        if isinstance(model, str) and model:
            return model
        return None
    return None

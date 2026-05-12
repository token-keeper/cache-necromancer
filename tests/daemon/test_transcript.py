"""Tests for daemon.transcript — bounded tail + extract_last_turn_usage."""
import json
from pathlib import Path

import pytest


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_extract_returns_none_for_missing_path(tmp_path):
    from daemon.transcript import extract_last_turn_usage

    missing = tmp_path / "nope.jsonl"
    assert extract_last_turn_usage(missing) is None


def test_extract_returns_none_for_none_input():
    from daemon.transcript import extract_last_turn_usage

    assert extract_last_turn_usage(None) is None


def test_extract_returns_none_when_no_assistant(tmp_path):
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "user", "message": {"content": "still hi"}},
    ])
    assert extract_last_turn_usage(path) is None


def test_extract_finds_usage_in_assistant_entry(tmp_path):
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"type": "user", "message": {"content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "cache_read_input_tokens": 45844,
                    "cache_creation_input_tokens": 0,
                    "input_tokens": 5,
                    "output_tokens": 12,
                },
            },
        },
    ])
    usage = extract_last_turn_usage(path)
    assert usage is not None
    assert usage["cache_read_input_tokens"] == 45844


def test_extract_picks_most_recent_assistant(tmp_path):
    """여러 assistant 중 가장 마지막 사용."""
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"type": "assistant", "message": {"usage": {"cache_read_input_tokens": 100}}},
        {"type": "user", "message": {"content": "next"}},
        {"type": "assistant", "message": {"usage": {"cache_read_input_tokens": 200}}},
    ])
    usage = extract_last_turn_usage(path)
    assert usage["cache_read_input_tokens"] == 200


def test_extract_falls_back_to_top_level_usage(tmp_path):
    """일부 transcript 포맷은 entry.usage 에 직접 — fallback 경로."""
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"role": "assistant", "usage": {"cache_read_input_tokens": 999}},
    ])
    usage = extract_last_turn_usage(path)
    assert usage["cache_read_input_tokens"] == 999


def test_extract_skips_malformed_json_lines(tmp_path):
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    path.write_text(
        "not-json\n"
        + json.dumps({"type": "assistant", "message": {"usage": {"cache_read_input_tokens": 50}}})
        + "\nalso-not-json\n",
        encoding="utf-8",
    )
    usage = extract_last_turn_usage(path)
    assert usage is not None
    assert usage["cache_read_input_tokens"] == 50


def test_extract_bounded_to_tail_64kb(tmp_path):
    """64KB 초과 파일에서도 마지막 turn은 잡힘."""
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "big.jsonl"
    # 큰 잡음 entries (각 ~1KB) * 100 = 100KB 분량 → 64KB tail 안에서 검색
    with open(path, "w", encoding="utf-8") as f:
        for i in range(100):
            f.write(
                json.dumps({"type": "user", "padding": "x" * 900, "i": i}) + "\n"
            )
        f.write(
            json.dumps({
                "type": "assistant",
                "message": {"usage": {"cache_read_input_tokens": 12345}},
            }) + "\n"
        )

    usage = extract_last_turn_usage(path)
    assert usage is not None
    assert usage["cache_read_input_tokens"] == 12345


def test_extract_returns_none_when_all_assistant_lack_usage(tmp_path):
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"type": "assistant", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"content": "hi2"}},
    ])
    assert extract_last_turn_usage(path) is None


def test_extract_handles_permission_error(tmp_path):
    """파일 읽기 OSError/PermissionError → None (Stop hook 안전 보장)."""
    from daemon.transcript import extract_last_turn_usage
    from unittest.mock import patch

    path = tmp_path / "t.jsonl"
    path.write_text('{"type":"assistant","message":{"usage":{"cache_read_input_tokens":1}}}', encoding="utf-8")

    with patch("daemon.transcript._read_tail", side_effect=PermissionError("denied")):
        assert extract_last_turn_usage(path) is None


def test_extract_under_100ms_for_typical_file(tmp_path):
    """Stop hook 보장 — 64KB 파일도 100ms 이내."""
    import time
    from daemon.transcript import extract_last_turn_usage

    path = tmp_path / "t.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for i in range(60):
            f.write(
                json.dumps({"type": "user", "padding": "y" * 900, "i": i}) + "\n"
            )
        f.write(
            json.dumps({
                "type": "assistant",
                "message": {"usage": {"cache_read_input_tokens": 1}},
            }) + "\n"
        )

    start = time.monotonic()
    usage = extract_last_turn_usage(path)
    elapsed = time.monotonic() - start
    assert usage is not None
    assert elapsed < 0.1

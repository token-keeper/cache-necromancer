"""Tests for scripts/on_user_prompt.py (TECH_SPEC §5)."""
import io
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from scripts.on_user_prompt import main  # noqa: E402


def _set_stdin(monkeypatch, payload: dict | str | None) -> None:
    if payload is None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
    elif isinstance(payload, str):
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    else:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


class TestResetWakeCount:
    def test_resets_wake_count_to_zero(self, cn_root, monkeypatch):
        sid = "session-abc"
        sh = sanitize(sid)
        # 기존 marker 에 wake_count = 5
        Marker(sid_hash=sh, wake_count=5, latest_fire=12345, last_wake_at=999).save()

        _set_stdin(monkeypatch, {"session_id": sid})
        rc = main()
        assert rc == 0

        loaded = Marker.load(sh)
        assert loaded.wake_count == 0
        # 다른 필드 보존
        assert loaded.latest_fire == 12345
        assert loaded.last_wake_at == 999

    def test_creates_marker_when_missing(self, cn_root, monkeypatch):
        sid = "new-session"
        _set_stdin(monkeypatch, {"session_id": sid})
        rc = main()
        assert rc == 0
        # marker 생성됨 + wake_count = 0
        loaded = Marker.load(sanitize(sid))
        assert loaded.wake_count == 0


class TestLastPromptCapture:
    """v0.3.5: stdin payload 의 prompt 를 truncate 후 marker.last_prompt 저장."""

    def test_saves_short_prompt_as_is(self, cn_root, monkeypatch):
        sid = "short-prompt"
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": "hello world"})
        main()
        assert Marker.load(sanitize(sid)).last_prompt == "hello world"

    def test_truncates_long_prompt_to_40_chars(self, cn_root, monkeypatch):
        sid = "long-prompt"
        long_text = "x" * 100
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": long_text})
        main()
        loaded = Marker.load(sanitize(sid))
        # 40자 + … = 41자 (display 폭)
        assert loaded.last_prompt.endswith("…")
        assert len(loaded.last_prompt) == 41  # 40 + "…"

    def test_truncates_at_exactly_40_chars(self, cn_root, monkeypatch):
        sid = "edge-40"
        text_40 = "a" * 40
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": text_40})
        main()
        # 정확히 40 = truncate 안 함
        assert Marker.load(sanitize(sid)).last_prompt == text_40

    def test_takes_first_line_only(self, cn_root, monkeypatch):
        sid = "multiline"
        _set_stdin(monkeypatch, {
            "session_id": sid,
            "prompt": "첫 줄 내용\n두 번째 줄\n세 번째 줄",
        })
        main()
        assert Marker.load(sanitize(sid)).last_prompt == "첫 줄 내용"

    def test_empty_prompt_leaves_last_prompt_unchanged(self, cn_root, monkeypatch):
        """prompt 비어있을 시 기존 last_prompt 보존 (overwrite X)."""
        sid = "preserve"
        Marker(sid_hash=sanitize(sid), last_prompt="기존값").save()
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": ""})
        main()
        assert Marker.load(sanitize(sid)).last_prompt == "기존값"

    def test_missing_prompt_field_leaves_last_prompt_unchanged(self, cn_root, monkeypatch):
        sid = "no-prompt-field"
        Marker(sid_hash=sanitize(sid), last_prompt="기존값").save()
        _set_stdin(monkeypatch, {"session_id": sid})  # no prompt key
        main()
        assert Marker.load(sanitize(sid)).last_prompt == "기존값"

    def test_strips_control_chars(self, cn_root, monkeypatch):
        """프롬프트 안의 ANSI / control char 등은 제거."""
        sid = "with-ctrl"
        _set_stdin(monkeypatch, {
            "session_id": sid,
            "prompt": "안녕\x00\x07\x1b[31m빨강",
        })
        main()
        loaded = Marker.load(sanitize(sid))
        # control char 가 제거되어야 함 (ANSI escape 의 `\x1b` 와 `\x00`, `\x07` 등)
        assert "\x00" not in loaded.last_prompt
        assert "\x1b" not in loaded.last_prompt
        assert "\x07" not in loaded.last_prompt


class TestPingSelfInterference:
    """v0.3.11: refresh.py 의 PING 도 prompt 로 hook 에 도달 →
    wake_count 가 reset 되어 매 wake 마다 '1/N' 무한 반복하던 버그 회귀 방지.
    """

    def test_ping_prefix_skips_wake_count_reset(self, cn_root, monkeypatch):
        sid = "ping-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, wake_count=3, last_prompt="기존").save()

        ping = "[cn:keepalive 14:30 KST, 4/10] reply with exactly 'ok @14:30 (4/10)'."
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": ping})
        assert main() == 0

        loaded = Marker.load(sh)
        assert loaded.wake_count == 3  # reset 안 됨
        assert loaded.last_prompt == "기존"  # 갱신 안 됨

    def test_ping_prefix_skips_even_when_marker_missing(self, cn_root, monkeypatch):
        """PING 만 들어오고 marker 없을 시 marker 새로 만들지도 않음."""
        sid = "ping-no-marker"
        ping = "[cn:keepalive 09:00 KST, 1/10] reply..."
        _set_stdin(monkeypatch, {"session_id": sid, "prompt": ping})
        assert main() == 0
        # marker file 생성 안 되어야 함 (PING 으로 인한 부수효과 X)
        from lib.marker import marker_path
        assert not marker_path(sanitize(sid)).exists()

    def test_normal_prompt_still_resets(self, cn_root, monkeypatch):
        """regression: PING 아닌 일반 prompt 는 그대로 reset 동작."""
        sid = "normal-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, wake_count=5).save()

        _set_stdin(monkeypatch, {"session_id": sid, "prompt": "안녕 클로드"})
        assert main() == 0
        assert Marker.load(sh).wake_count == 0


class TestEdgeCases:
    def test_no_session_id_returns_silently(self, cn_root, monkeypatch):
        _set_stdin(monkeypatch, {})
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert main() == 0

    def test_invalid_json_returns_silently(self, cn_root, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _set_stdin(monkeypatch, "not json {")
        assert main() == 0

    def test_session_id_from_env_when_stdin_missing(self, cn_root, monkeypatch):
        sid = "env-session"
        sh = sanitize(sid)
        Marker(sid_hash=sh, wake_count=3).save()

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _set_stdin(monkeypatch, "")
        assert main() == 0
        assert Marker.load(sh).wake_count == 0

    def test_marker_save_failure_returns_0(self, cn_root, monkeypatch):
        """save 실패해도 chat 영향 X (exit 0)."""
        sid = "fail-session"
        _set_stdin(monkeypatch, {"session_id": sid})
        from lib.marker import Marker as M

        def bad_save(self):
            raise OSError("simulated")

        monkeypatch.setattr(M, "save", bad_save)
        assert main() == 0

    def test_stdin_session_id_takes_priority_over_env(self, cn_root, monkeypatch):
        """stdin 과 env 둘 다 있으면 stdin 우선 (TECH_SPEC §5)."""
        stdin_sid = "stdin-session"
        env_sid = "env-session"
        # 두 marker 미리 wake_count = 5
        Marker(sid_hash=sanitize(stdin_sid), wake_count=5).save()
        Marker(sid_hash=sanitize(env_sid), wake_count=5).save()

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", env_sid)
        _set_stdin(monkeypatch, {"session_id": stdin_sid})
        assert main() == 0

        # stdin 의 marker 만 reset
        assert Marker.load(sanitize(stdin_sid)).wake_count == 0
        assert Marker.load(sanitize(env_sid)).wake_count == 5

#!/usr/bin/env python3
"""Stop hook 의 sync 본체 — turn 종료 즉시 recap 영역에 다음 wake 시각 표시.

출력 형식:
  1줄: 🪦 캐시 만료 시각 (항상)
  2줄: 🔥 set 예산 잔량 + 최대 생존 시한 (set_budget_remaining > 0 일 때만)

design spec: docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md
PRD 불변: 어떤 실패도 chat 동작 차단 X (silent fail).
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.box_render import render_box  # noqa: E402
from lib.config import ensure_config_file, load_config  # noqa: E402
from lib.i18n import (  # noqa: E402
    build_lives_recap_line,
    build_recap_message,
    build_revived_message,
    build_set_recap_line,
    normalize_language,
)
from lib.install_version import is_latest_install  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _read_hook_input() -> dict:
    """Stop hook stdin payload(JSON) 1회 read. 실패 시 빈 dict."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _resolve_session_id(payload: dict) -> str:
    sid = payload.get("session_id", "")
    if sid:
        return sid
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


_KEEPALIVE_NM = re.compile(r"[\s,](\d+)/\d+")


def detect_wake_turn(transcript_path: str) -> tuple[bool, int]:
    """transcript tail 의 최신 user 엔트리가 cn keepalive 면 (True, N).

    N = ping 의 (N/M) 에서 파싱(없으면 1). 실패/미존재 시 (False, 0).
    """
    if not transcript_path:
        return (False, 0)
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 65536))
            data = f.read()
    except OSError:
        return (False, 0)
    last_user: dict | None = None
    for raw in data.splitlines():
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and e.get("type") == "user":
            last_user = e
    if last_user is None or not last_user.get("isMeta"):
        return (False, 0)
    msg = last_user.get("message") or {}
    content = msg.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if "[cn:keepalive" not in text:
        return (False, 0)
    m = _KEEPALIVE_NM.search(text)
    return (True, int(m.group(1)) if m else 1)


def _main_impl() -> int:
    if not is_latest_install():
        return 0
    payload = _read_hook_input()
    sid = _resolve_session_id(payload)
    if not sid:
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0

    config_path = _resolve_root() / "config.toml"
    try:
        ensure_config_file(config_path)
        config = load_config(config_path)
    except (OSError, ValueError):
        return 0

    ttl = config.cache_ttl_minutes
    if not isinstance(ttl, int) or ttl <= 0:
        return 0

    lang = normalize_language(config.language)
    now = datetime.now()
    death_at = now + timedelta(minutes=ttl)

    wake, revive_n = detect_wake_turn(payload.get("transcript_path", ""))
    if wake:
        line1 = build_revived_message(lang, revive_n, death_at.hour, death_at.minute)
    else:
        line1 = build_recap_message(lang, death_at.hour, death_at.minute)
    lines = [line1]

    marker = Marker.load(sid_hash)
    if config.wake.arm == "always":
        # always: 남은 목숨(max - wake_count) + idle 시 최대 생존 시한
        lives = max(0, config.max_refresh_count - marker.wake_count)
        survive_at = now + timedelta(
            minutes=lives * config.refresh_interval_minutes + ttl
        )
        lines.append(
            build_lives_recap_line(lang, lives, survive_at.hour, survive_at.minute)
        )
    elif marker.set_budget_remaining > 0:
        survive_at = now + timedelta(
            minutes=marker.set_budget_remaining * config.refresh_interval_minutes + ttl
        )
        lines.append(
            build_set_recap_line(
                lang, marker.set_budget_remaining, survive_at.hour, survive_at.minute
            )
        )

    if config.display.recap_style == "box":
        # Claude Code 가 systemMessage 첫 줄에 "Stop says: " prefix 를 붙여
        # top border 만 우측으로 밀려 body 줄과 어긋난다. 선두 개행으로
        # 박스를 제 줄에서 시작시켜 정렬을 맞춘다.
        message = "\n" + render_box(lines)
    else:
        message = "\n".join(lines)

    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())

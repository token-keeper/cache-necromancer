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
import sys
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import ensure_config_file, load_config  # noqa: E402
from lib.i18n import build_recap_message, build_set_recap_line, normalize_language  # noqa: E402
from lib.install_version import is_latest_install  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


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
    if not is_latest_install():
        return 0
    sid = _resolve_session_id()
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
    message = build_recap_message(lang, death_at.hour, death_at.minute)

    # 2줄째 — set 예산 잔량 (spec §8). 예산 > 0 일 때만 표시.
    marker = Marker.load(sid_hash)
    if marker.set_budget_remaining > 0:
        survive_at = now + timedelta(
            minutes=marker.set_budget_remaining * config.refresh_interval_minutes + ttl
        )
        message += "\n" + build_set_recap_line(
            lang, marker.set_budget_remaining, survive_at.hour, survive_at.minute
        )

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

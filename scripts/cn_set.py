#!/usr/bin/env python3
"""/cn:set backend (spec §4) — 현재 세션 wake 예산 충전/취소/조회.

UserPromptExpansion(on_status_command.py) 또는 commands/cn:set.md fallback 이
argv 로 인자를 넘긴다. 출력은 stdout plain text (LLM turn 0회).
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import Config, ensure_config_file, load_config  # noqa: E402
from lib.i18n import normalize_language, set_label  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _survive_time(config: Config, remaining: int) -> str:
    at = datetime.now() + timedelta(
        minutes=remaining * config.refresh_interval_minutes + config.cache_ttl_minutes
    )
    return at.strftime("%H:%M")


def main(argv: list[str]) -> int:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        print("session_id 없음 — chat 세션 안에서 실행하세요.")
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
        config = Config()
    lang = normalize_language(config.language)
    marker = Marker.load(sid_hash)

    arg = argv[0].strip() if argv else None

    # 무인자 — 상태 조회
    if arg is None:
        if marker.set_budget_remaining > 0:
            print(set_label(lang, "status_armed").format(
                n=marker.set_budget_remaining,
                total=marker.set_budget_total,
                time=_survive_time(config, marker.set_budget_remaining),
            ))
        else:
            print(set_label(lang, "status_none"))
        return 0

    if not arg.isdigit():                     # 음수/소수/문자 → usage
        print(set_label(lang, "usage"))
        return 0
    n = int(arg)

    if config.wake.arm == "always":
        print(set_label(lang, "always_noop"))
        return 0

    if n == 0:
        marker.set_budget_remaining = 0
        marker.set_budget_total = 0
        marker.save()
        print(set_label(lang, "cancelled"))
        return 0

    charged = min(n, config.max_refresh_count)
    marker.set_budget_remaining = charged
    marker.set_budget_total = charged
    marker.set_charged_at_ns = time.time_ns()
    marker.save()

    lines = [set_label(lang, "charged").format(
        n=charged, time=_survive_time(config, charged))]
    if charged < n:
        lines.append(set_label(lang, "capped_note").format(
            req=n, max=config.max_refresh_count))
    lines.append(set_label(lang, "session_only"))
    if marker.latest_fire == 0:
        lines.append(set_label(lang, "first_turn_note"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

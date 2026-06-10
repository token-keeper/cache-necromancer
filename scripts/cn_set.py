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
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _save_or_fail(marker: Marker) -> bool:
    """save 실패 시 경고 출력 + False (성공 메시지 출력 금지 — 미반영 상태)."""
    try:
        marker.save()
        return True
    except OSError as e:
        log_warn(f"[cn_set] marker save 실패: {type(e).__name__}: {e}")
        print("⚠️  marker 저장 실패 — set 이 적용되지 않았습니다. 다시 시도하세요.")
        return False


def _survive_time(config: Config, remaining: int) -> str:
    at = datetime.now() + timedelta(
        minutes=remaining * config.refresh_interval_minutes + config.cache_ttl_minutes
    )
    return at.strftime("%H:%M")


def _no_live_timer(marker: Marker, config: Config) -> bool:
    """pending refresh timer 부재 추정 — latest_fire 가 없거나 이미 소진(만료)됨."""
    if marker.latest_fire == 0:
        return True
    interval_ns = config.refresh_interval_minutes * 60 * 1_000_000_000
    return time.time_ns() > marker.latest_fire + interval_ns


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

    if not arg.isdecimal():                   # 음수/소수/문자/위첨자 → usage
        print(set_label(lang, "usage"))
        return 0
    n = int(arg)

    if config.wake.arm == "always":
        print(set_label(lang, "always_noop"))
        return 0

    if n == 0:
        marker.set_budget_remaining = 0
        marker.set_budget_total = 0
        if not _save_or_fail(marker):
            return 0
        print(set_label(lang, "cancelled"))
        return 0

    charged = min(n, config.max_refresh_count)
    marker.set_budget_remaining = charged
    marker.set_budget_total = charged
    marker.set_charged_at_ns = time.time_ns()
    if not _save_or_fail(marker):
        return 0

    lines = [set_label(lang, "charged").format(
        n=charged, time=_survive_time(config, charged))]
    if charged < n:
        lines.append(set_label(lang, "capped_note").format(
            req=n, max=config.max_refresh_count))
    lines.append(set_label(lang, "session_only"))
    if _no_live_timer(marker, config):
        lines.append(set_label(lang, "first_turn_note"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

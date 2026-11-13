#!/usr/bin/env python3
"""/cn:set backend (v0.12.0) — 현재 세션 깨우기 덮어쓰기·끄기·조회.

  - /cn:set N(≥1): 이번 자리비움 깨우기를 N회로 덮어쓴다 (상한 SET_CAP). wake_off 해제.
  - /cn:set 0 · off: 이 세션 깨우기를 세션 끝까지 끈다.
  - /cn:set: 상태 조회.

UserPromptExpansion(on_status_command.py) 또는 commands/cn:set.md fallback 이
argv 로 인자를 넘긴다. 출력은 stdout plain text (LLM turn 0회).
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import SET_CAP, Config, ensure_config_file, load_config  # noqa: E402
from lib.i18n import Language, normalize_language, set_label  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.wake_plan import cache_expired, remaining_wakes, survive_until_ns, wake_mode  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _save_or_fail(marker: Marker, lang: Language) -> bool:
    """save 실패 시 경고 출력 + False (성공 메시지 출력 금지 — 미반영 상태)."""
    try:
        marker.save()
        return True
    except OSError as e:
        log_warn(f"[cn_set] marker save 실패: {type(e).__name__}: {e}")
        print(set_label(lang, "save_failed"))
        return False


def _until(marker: Marker, config: Config, lang: Language) -> str:
    """"캐시 최대 HH:MM까지" — 캐시가 이미 만료됐으면(깨우기 창이 지남) 시각 대신 만료 안내."""
    now = time.time_ns()
    if cache_expired(marker.latest_fire, now, config):
        return set_label(lang, "until_expired")
    ns = survive_until_ns(marker.latest_fire or now, remaining_wakes(marker, config), config)
    hhmm = datetime.fromtimestamp(ns / 1_000_000_000).strftime("%H:%M")
    return set_label(lang, "until_time").format(time=hhmm)


def _status(marker: Marker, config: Config, lang: Language) -> str:
    mode = wake_mode(marker)
    if mode == "off":
        return set_label(lang, "status_off")
    if mode == "auto" and config.auto_wakes == 0:
        return set_label(lang, "status_auto_disabled")
    key = "status_set" if mode == "set" else "status_auto"
    return set_label(lang, key).format(
        n=remaining_wakes(marker, config), until=_until(marker, config, lang)
    )


def main(argv: list[str]) -> int:
    config_path = _resolve_root() / "config.toml"
    try:
        ensure_config_file(config_path)
    except OSError:
        pass
    config = load_config(config_path)
    lang = normalize_language(config.language)

    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        print(set_label(lang, "no_session"))
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0
    marker = Marker.load(sid_hash)

    arg = argv[0].strip() if argv else None

    if arg is None:                            # 상태 조회
        print(_status(marker, config, lang))
        return 0

    if arg.lower() == "off" or (arg.isdecimal() and int(arg) == 0):
        marker.wake_off = True
        marker.set_budget_remaining = 0
        marker.set_budget_total = 0
        marker.set_charged_at_ns = 0
        if _save_or_fail(marker, lang):
            print(set_label(lang, "turned_off"))
        return 0

    if not arg.isdecimal():                    # 음수/소수/문자 → usage
        print(set_label(lang, "usage"))
        return 0
    n = int(arg)

    charged = min(n, SET_CAP)
    marker.set_budget_remaining = charged
    marker.set_budget_total = charged
    marker.set_charged_at_ns = time.time_ns()
    marker.wake_off = False
    if not _save_or_fail(marker, lang):
        return 0

    lines = [set_label(lang, "charged").format(
        n=charged, until=_until(marker, config, lang))]
    if n > SET_CAP:
        lines.append(set_label(lang, "capped_note").format(max=SET_CAP))
    lines.append(set_label(lang, "session_only"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

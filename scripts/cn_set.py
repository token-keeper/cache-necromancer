#!/usr/bin/env python3
"""/cn:set backend (v0.13.0) — 현재 세션 깨우기 덮어쓰기·끄기·조회.

  - /cn:set N(≥1): 이번 자리비움 깨우기를 N회로 덮어쓴다 (상한 SET_CAP). wake_off 해제.
  - /cn:set 0 · off: 이 세션 깨우기를 세션 끝까지 끈다.
  - /cn:set auto: 덮어쓰기·끄기를 풀고 자동으로 (v0.13.0).
  - /cn:set 2h · 90m · 1h30m · 18:00: 그 시각까지 살리는 데 필요한 횟수를 계산해 충전 (v0.13.0).
  - /cn:set: 상태 조회.

UserPromptExpansion(on_status_command.py) 또는 commands/cn:set.md fallback 이
argv 로 인자를 넘긴다. 출력은 stdout plain text (LLM turn 0회).
"""
import os
import re
import sys
import time
from datetime import datetime, timedelta
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
from lib.wake_plan import (  # noqa: E402
    cache_expired,
    can_wake,
    remaining_wakes,
    survive_until_ns,
    wake_mode,
    wakes_for_target,
)

_MIN_NS = 60 * 1_000_000_000
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _save_or_fail(marker: Marker, lang: Language) -> bool:
    """save 실패 시 경고 출력 + False (성공 메시지 출력 금지 — 미반영 상태). 호출부는 exit 1."""
    try:
        marker.save()
        return True
    except OSError as e:
        log_warn(f"[cn_set] marker save 실패: {type(e).__name__}: {e}")
        print(set_label(lang, "save_failed"))
        return False


def _hhmm(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000).strftime("%H:%M")


def _until(marker: Marker, config: Config, lang: Language) -> str:
    """"캐시 최대 HH:MM까지" — 캐시가 이미 만료됐으면(깨우기 창이 지남) 시각 대신 만료 안내."""
    now = time.time_ns()
    if cache_expired(marker.latest_fire, now, config):
        return set_label(lang, "until_expired")
    ns = survive_until_ns(marker.latest_fire or now, remaining_wakes(marker, config), config)
    return set_label(lang, "until_time").format(time=_hhmm(ns))


def _status(marker: Marker, config: Config, lang: Language) -> str:
    mode = wake_mode(marker)
    if mode == "off":
        return set_label(lang, "status_off")
    if not can_wake(config):  # 띠(register.tsx extraFor)처럼 남은 횟수를 보이지 않는다
        return set_label(lang, "no_window")
    if mode == "auto" and config.auto_wakes == 0:
        return set_label(lang, "status_auto_disabled")
    key = "status_set" if mode == "set" else "status_auto"
    return set_label(lang, key).format(
        n=remaining_wakes(marker, config), until=_until(marker, config, lang)
    )


def _target_ns(arg: str, now_ns: int) -> "int | None":
    """`2h`·`90m`·`1h30m`(지금부터, 합계 ≥1분) · `18:00`(오늘 로컬, 지났으면 내일) → 목표 ns.
    형식이 아니면 None."""
    m = _DURATION_RE.match(arg)
    if m:
        minutes = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        return now_ns + minutes * _MIN_NS if minutes >= 1 else None
    m = _CLOCK_RE.match(arg)
    if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
        now = datetime.fromtimestamp(now_ns / 1_000_000_000)
        t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return int(t.timestamp()) * 1_000_000_000
    return None


def _charge(marker: Marker, config: Config, lang: Language, n: int) -> int:
    """이번 자리비움 깨우기를 n회(상한 SET_CAP)로 덮어쓰고 안내."""
    charged = min(n, SET_CAP)
    marker.set_budget_remaining = charged
    marker.set_budget_total = charged
    marker.set_charged_at_ns = time.time_ns()
    marker.wake_off = False
    if not _save_or_fail(marker, lang):
        return 1
    if not can_wake(config):  # 충전은 저장하되 깨울 수 없으니 횟수는 보이지 않는다 (띠와 같게)
        lines = [set_label(lang, "no_window")]
    else:
        lines = [set_label(lang, "charged").format(n=charged, until=_until(marker, config, lang))]
        if n > SET_CAP:
            lines.append(set_label(lang, "capped_note").format(max=SET_CAP))
    lines.append(set_label(lang, "session_only"))
    print("\n".join(lines))
    return 0


def _charge_until(marker: Marker, config: Config, lang: Language, target_ns: int) -> int:
    """목표 시각까지 살리는 데 필요한 횟수만큼 충전. 기준 = latest_fire (없거나 만료면 지금)."""
    if not can_wake(config):
        print(set_label(lang, "no_window"))
        return 0
    now = time.time_ns()
    live = marker.latest_fire > 0 and not cache_expired(marker.latest_fire, now, config)
    anchor = marker.latest_fire if live else now
    n = wakes_for_target(anchor, target_ns, config)
    if n <= 0:
        if live:
            alive = survive_until_ns(anchor, 0, config)
            print(set_label(lang, "already_alive").format(time=_hhmm(alive)))
        else:  # 기준을 now 로 대신했을 뿐 살아 있는 캐시는 없다 — 생존 시각을 약속하지 않는다
            print(set_label(lang, "no_live_cache"))
        return 0
    return _charge(marker, config, lang, n)


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
        if not _save_or_fail(marker, lang):
            return 1
        print(set_label(lang, "turned_off"))
        return 0

    if arg.lower() == "auto":
        marker.wake_off = False
        marker.set_budget_remaining = 0
        marker.set_budget_total = 0
        marker.set_charged_at_ns = 0
        if not _save_or_fail(marker, lang):
            return 1
        print(set_label(lang, "back_to_auto") + "\n" + _status(marker, config, lang))
        return 0

    if arg.isdecimal():
        return _charge(marker, config, lang, int(arg))

    target = _target_ns(arg.lower(), time.time_ns())
    if target is None:                         # 음수/소수/문자 → usage
        print(set_label(lang, "usage"))
        return 0
    return _charge_until(marker, config, lang, target)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

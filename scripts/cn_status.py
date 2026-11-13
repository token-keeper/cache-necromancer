#!/usr/bin/env python3
"""/cn:status backend (v0.12.0).

  - 현재 세션: 깨우기 상태(off/덮어쓰기/자동) + 남은 횟수 + 살린 횟수 + 다음 깨우기 + 캐시 최대 생존 시각
  - 다른 세션: 다음 깨우기 / prompt / cwd — active 판정은 생존 시각(lib/wake_plan) 기준
  - 상태: 자동 깨우기 · interval/ttl · plugin, 옛 설정 키가 있으면 한 줄 경고
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.box_renderer import box_section, display_width, wrap_outer  # noqa: E402
from lib.config import Config, detect_obsolete_keys, load_config, parse_config_file  # noqa: E402
from lib.i18n import normalize_language, status_label  # noqa: E402
from lib.marker import Marker, marker_dir  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.wake_plan import (  # noqa: E402
    cache_expired,
    can_wake,
    remaining_wakes,
    survive_until_ns,
    wake_mode,
)

OTHER_SESSIONS_MAX_SHOW = 5

_PLUGIN_VERSION_CACHE: str | None = None


def _plugin_version() -> str:
    """plugin.json 에서 version 동적 읽기. 실패 시 'unknown'."""
    global _PLUGIN_VERSION_CACHE
    if _PLUGIN_VERSION_CACHE is not None:
        return _PLUGIN_VERSION_CACHE
    try:
        data = json.loads(
            (_PROJECT_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        _PLUGIN_VERSION_CACHE = str(data.get("version", "unknown"))
    except (json.JSONDecodeError, OSError):
        _PLUGIN_VERSION_CACHE = "unknown"
    return _PLUGIN_VERSION_CACHE


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _current_sid_hash() -> str | None:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    try:
        return sanitize(sid)
    except ValueError:
        return None


def _format_delta(target: datetime, now: datetime) -> str:
    delta = (target - now).total_seconds()
    sign = "-" if delta < 0 else ""
    delta = abs(delta)
    if delta < 60:
        return f"{sign}{int(delta)}s"
    m, s = divmod(int(delta), 60)
    if m < 60:
        return f"{sign}{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{sign}{h}h {m}m"


def _list_markers() -> list[Marker]:
    d = marker_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        out.append(Marker.load(p.stem))
    return out


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).astimezone()


def _next_wake_dt(marker: Marker, config: Config) -> datetime | None:
    """다음 깨우기 예상 시각 (마지막 Stop + interval). 깨울 수 없으면 None."""
    if (marker.latest_fire <= 0 or remaining_wakes(marker, config) == 0
            or not can_wake(config) or _expired(marker, config)):
        return None
    return _ns_to_dt(marker.latest_fire + config.refresh_interval_minutes * 60 * 1_000_000_000)


def _expired(marker: Marker, config: Config) -> bool:
    return cache_expired(marker.latest_fire, time.time_ns(), config)


def _survive_dt(marker: Marker, config: Config, now: datetime) -> datetime:
    anchor = marker.latest_fire or int(now.timestamp() * 1_000_000_000)
    return _ns_to_dt(survive_until_ns(anchor, remaining_wakes(marker, config), config))


def _abbrev_home(path: str) -> str:
    """홈 디렉터리 prefix → ~ 단축. 빈 문자열은 그대로."""
    if not path:
        return ""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def _compute_pad(labels: list[str]) -> int:
    """가장 긴 라벨 + ':' + 공백 1자 — display_width 기반 (CJK 폭 정확)."""
    return max(display_width(lbl) for lbl in labels) + 2


def _row(label: str, value: str, pad: int) -> str:
    """`label:` + value 정렬. pad 안에 라벨 + ':' + 공백 분량 들어감."""
    return f"{label}:{' ' * (pad - display_width(label) - 1)}{value}"


def _wake_state(marker: Marker, config: Config, lang) -> str:
    mode = wake_mode(marker)
    if mode == "off":
        return status_label(lang, "state_off")
    if not can_wake(config):  # 띠(register.tsx extraFor)처럼 남은 횟수를 보이지 않는다
        return status_label(lang, "state_no_window")
    key = "state_set" if mode == "set" else "state_auto"
    return status_label(lang, key).format(n=remaining_wakes(marker, config))


def _build_session_box(marker: Marker, config: Config, now: datetime, lang) -> list[str]:
    """현재 세션 박스 (i18n)."""
    L_sid = status_label(lang, "sid")
    L_wake = status_label(lang, "wake")
    L_woken = status_label(lang, "woken")
    L_next = status_label(lang, "next_wake")
    L_alive = status_label(lang, "alive_until")
    pad = _compute_pad([L_sid, L_wake, L_woken, L_next, L_alive])

    lines = [
        _row(L_sid, mask_sid(marker.sid_hash), pad),
        _row(L_wake, _wake_state(marker, config, lang), pad),
        _row(L_woken, status_label(lang, "woken_value").format(n=marker.wake_count), pad),
    ]
    next_dt = _next_wake_dt(marker, config)
    if next_dt is not None:
        lines.append(_row(
            L_next,
            f"{next_dt.strftime('%Y-%m-%d %H:%M:%S')} ({_format_delta(next_dt, now)})",
            pad,
        ))
    if marker.latest_fire > 0:
        alive = (status_label(lang, "expired") if _expired(marker, config)
                 else _survive_dt(marker, config, now).strftime("%H:%M"))
        lines.append(_row(L_alive, alive, pad))
    return box_section(status_label(lang, "current_session"), lines)


def _other_session_lines(marker: Marker, config: Config, now: datetime, lang) -> list[str]:
    """다른 세션 inner 박스 본문 — next_wake / prompt / cwd."""
    L_next = status_label(lang, "next_wake")
    L_prompt = status_label(lang, "prompt")
    L_cwd = status_label(lang, "cwd")
    pad = _compute_pad([L_next, L_prompt, L_cwd])

    next_dt = _next_wake_dt(marker, config)
    if next_dt is not None:
        next_val = f"{next_dt.strftime('%H:%M:%S')} ({_format_delta(next_dt, now)})"
    else:
        next_val = "—"

    prompt = marker.last_prompt if marker.last_prompt else "—"
    cwd = _abbrev_home(marker.cwd) if marker.cwd else "—"

    return [
        _row(L_next, next_val, pad),
        _row(L_prompt, f'"{prompt}"', pad),
        _row(L_cwd, cwd, pad),
    ]


def _is_active(marker: Marker, config: Config, now: datetime) -> bool:
    """캐시가 아직 살아 있어야 active (마지막 Stop + ttl 이 미래).

    깨우면 ping turn 의 Stop 이 latest_fire 를 다시 올리므로, 연쇄 중인 세션은 항상
    여기에 걸린다. Stop 기록이 없거나 이미 만료된 세션은 표시에서 뺀다
    (cleanup_stale 7d 정책과 별개로 표시만 필터링).
    """
    return marker.latest_fire > 0 and not _expired(marker, config)


def _build_other_sessions_box(
    others: list[Marker], config: Config, now: datetime, lang
) -> list[str]:
    """다른 세션 outer 박스 + sid 별 inner 박스."""
    active = [m for m in others if _is_active(m, config, now)]
    title = status_label(lang, "other_sessions")
    if not active:
        return wrap_outer(title, [status_label(lang, "no_other")])

    sorted_others = sorted(active, key=lambda m: m.latest_fire, reverse=True)
    shown = sorted_others[:OTHER_SESSIONS_MAX_SHOW]

    titles_and_lines = [
        (mask_sid(m.sid_hash), _other_session_lines(m, config, now, lang)) for m in shown
    ]
    natural_widths = []
    for t, lines in titles_and_lines:
        body_max = max(display_width(l) for l in lines) if lines else 0
        title_w = display_width(f"─ {t} ")
        natural_widths.append(max(body_max + 2, title_w + 2))
    target_inner = max(natural_widths)

    combined: list[str] = []
    for i, (t, lines) in enumerate(titles_and_lines):
        if i > 0:
            combined.append("")
        combined.extend(box_section(t, lines, min_width=target_inner))

    if len(sorted_others) > OTHER_SESSIONS_MAX_SHOW:
        combined.append("")
        combined.append(
            status_label(lang, "more_n").format(
                n=len(sorted_others) - OTHER_SESSIONS_MAX_SHOW
            )
        )

    return wrap_outer(title, combined)


def _build_status_box(config: Config, lang, obsolete_keys: list[str]) -> list[str]:
    """상태 박스 — 자동 깨우기 / 설정 / plugin (+ 옛 설정 경고 한 줄)."""
    L_auto = status_label(lang, "auto_wakes")
    L_settings = status_label(lang, "settings")
    L_plugin = status_label(lang, "plugin")
    pad = _compute_pad([L_auto, L_settings, L_plugin])

    if config.auto_wakes > 0:
        auto_text = status_label(lang, "auto_per_away").format(n=config.auto_wakes)
    else:
        auto_text = status_label(lang, "auto_disabled")
    settings_text = status_label(lang, "settings_value").format(
        i=config.refresh_interval_minutes, t=config.cache_ttl_minutes
    )
    plugin_text = f"cache-necromancer v{_plugin_version()} (active)"

    lines = [
        _row(L_auto, auto_text, pad),
        _row(L_settings, settings_text, pad),
        _row(L_plugin, plugin_text, pad),
    ]
    # 키 이름은 나열하지 않는다 — 박스 폭 보호
    if obsolete_keys:
        lines.append(status_label(lang, "obsolete_warn").format(n=len(obsolete_keys)))
    return box_section(status_label(lang, "status"), lines)


def main() -> int:
    config_path = _resolve_root() / "config.toml"
    # 옛 키 감지용 raw parse (load_config 와 별도 — side effect 없음)
    raw_data, _err = parse_config_file(config_path)
    obsolete_keys = detect_obsolete_keys(raw_data)
    config = load_config(config_path)

    lang = normalize_language(config.language)
    now = datetime.now(timezone.utc).astimezone()
    current_hash = _current_sid_hash()
    markers = _list_markers()

    current = None
    others = []
    for m in markers:
        if current_hash and m.sid_hash == current_hash:
            current = m
        else:
            others.append(m)
    if current is None and current_hash:
        current = Marker(sid_hash=current_hash)

    body: list[str] = []
    if current:
        body.extend(_build_session_box(current, config, now, lang))
        body.append("")
    body.extend(_build_other_sessions_box(others, config, now, lang))
    body.append("")
    body.extend(_build_status_box(config, lang, obsolete_keys))

    print("\n".join(wrap_outer(status_label(lang, "title"), body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

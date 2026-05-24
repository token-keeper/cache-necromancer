#!/usr/bin/env python3
"""/cn:status backend (TECH_SPEC §8).

v0.3.13: 박스 재구성 + i18n (ko/en/ja/zh).
  - 상단 mode 줄 제거 → "상태" 박스 안으로
  - 다른 세션: 라벨 통일 (next_fire / prompt / cwd 3줄)
  - 설정 박스 → "상태" 박스로 rename. hook 등록 / deprecated config 제거
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.box_renderer import box_section, display_width, wrap_outer  # noqa: E402
from lib.config import Config, load_config  # noqa: E402
from lib.i18n import (  # noqa: E402
    mode_label_i18n,
    normalize_language,
    status_label,
)
from lib.marker import Marker, marker_dir  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

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


def _ns_to_dt(ns: int, now: datetime) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).astimezone()


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


def _build_session_box(marker: Marker, config: Config, now: datetime, lang) -> list[str]:
    """현재 세션 박스 (i18n)."""
    masked = mask_sid(marker.sid_hash)
    L_sid = status_label(lang, "sid")
    L_count = status_label(lang, "repeat_count")
    L_next = status_label(lang, "next_fire")

    # 라벨 폭 정렬 — 가장 긴 라벨 + ":" + 공백
    labels = [L_sid, L_count, L_next]
    pad = max(display_width(lbl) for lbl in labels) + 2  # ":" + space

    def _row(label: str, value: str) -> str:
        return f"{label}:{' ' * (pad - display_width(label) - 1)}{value}"

    lines = [
        _row(L_sid, masked),
        _row(L_count, f"{marker.wake_count} / {config.max_refresh_count}"),
    ]
    if marker.latest_fire > 0:
        next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
            minutes=config.refresh_interval_minutes
        )
        lines.append(
            _row(
                L_next,
                f"{next_dt.strftime('%Y-%m-%d %H:%M:%S')} ({_format_delta(next_dt, now)})",
            )
        )

    return box_section(status_label(lang, "current_session"), lines)


def _other_session_lines(marker: Marker, config: Config, now: datetime, lang) -> list[str]:
    """다른 세션 inner 박스 본문 — next_fire / prompt / cwd."""
    L_next = status_label(lang, "next_fire")
    L_prompt = status_label(lang, "prompt")
    L_cwd = status_label(lang, "cwd")

    labels = [L_next, L_prompt, L_cwd]
    pad = max(display_width(lbl) for lbl in labels) + 2

    def _row(label: str, value: str) -> str:
        return f"{label}:{' ' * (pad - display_width(label) - 1)}{value}"

    if marker.latest_fire > 0:
        next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
            minutes=config.refresh_interval_minutes
        )
        next_val = f"{next_dt.strftime('%H:%M:%S')} ({_format_delta(next_dt, now)})"
    else:
        next_val = "—"

    prompt = marker.last_prompt if marker.last_prompt else "—"
    cwd = _abbrev_home(marker.cwd) if marker.cwd else "—"

    return [
        _row(L_next, next_val),
        _row(L_prompt, f'"{prompt}"'),
        _row(L_cwd, cwd),
    ]


def _is_active(marker: Marker, config: Config, now: datetime) -> bool:
    """다음 발동 예상 시각이 미래여야 active.

    latest_fire 가 과거고 거기서 refresh_interval 도 이미 지났으면 = wake
    cycle 종료된 stale 세션 (max_refresh_count 도달 또는 chat 종료). cn:status
    가시성에서 제외 (cleanup_stale 7d 정책과 별개로 표시만 필터링).
    """
    if marker.latest_fire <= 0:
        return False
    next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
        minutes=config.refresh_interval_minutes
    )
    return next_dt > now


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


def _build_status_box(config: Config, lang) -> list[str]:
    """상태 박스 — mode / settings / plugin (v0.3.13: rename from 설정 상태)."""
    L_mode = status_label(lang, "mode")
    L_settings = status_label(lang, "settings")
    L_plugin = status_label(lang, "plugin")

    labels = [L_mode, L_settings, L_plugin]
    pad = max(display_width(lbl) for lbl in labels) + 2

    def _row(label: str, value: str) -> str:
        return f"{label}:{' ' * (pad - display_width(label) - 1)}{value}"

    mode_text = mode_label_i18n(lang, config.mode, config.refresh.hybrid_wait_seconds)
    settings_text = (
        f"refresh {config.refresh_interval_minutes}m · max {config.max_refresh_count}"
    )
    plugin_text = f"cache-necromancer v{_plugin_version()} (active)"

    lines = [
        _row(L_mode, mode_text),
        _row(L_settings, settings_text),
        _row(L_plugin, plugin_text),
    ]
    if config.mode == "notify":
        lines.append(status_label(lang, "notify_warn"))
    return box_section(status_label(lang, "status"), lines)


def main() -> int:
    config_path = _resolve_root() / "config.toml"
    try:
        config = load_config(config_path)
    except ValueError as e:
        print(f"⚠️  config 로드 실패: {e}. 기본값 표시.", file=sys.stderr)
        config = Config()

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
        current = Marker(sid_hash=current_hash, session_started_at=int(time.time()))

    body: list[str] = []
    if current:
        body.extend(_build_session_box(current, config, now, lang))
        body.append("")
    body.extend(_build_other_sessions_box(others, config, now, lang))
    body.append("")
    body.extend(_build_status_box(config, lang))

    print("\n".join(wrap_outer(status_label(lang, "title"), body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

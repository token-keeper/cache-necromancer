#!/usr/bin/env python3
"""/cn:status backend (TECH_SPEC §8) — v0.3.0 출력.

마커 glob 으로 세션 목록 표시. 현재 세션 우선 + 다른 세션. 설정/플러그인 상태.
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
from lib.config import Config, detect_deprecated_keys, load_config, parse_config_file  # noqa: E402
from lib.marker import Marker, marker_dir, marker_path  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.mode_help import mode_label  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

CN_HOOK_MARKER = str(_PROJECT_ROOT / "scripts/refresh.py")
SETTINGS_FILES = ("settings.json", "settings.local.json")
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


def _resolve_claude_root() -> Path:
    root = os.environ.get("CN_CLAUDE_ROOT")
    return Path(root) if root else Path.home() / ".claude"


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


def _format_ts(unix_ts: int, now: datetime) -> str:
    if unix_ts == 0:
        return "—"
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone()
    rel = _format_delta(dt, now)
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} ({rel} 전)" if rel.startswith("-") \
        else f"{dt.strftime('%Y-%m-%d %H:%M:%S')} ({rel} 후)"


def _list_markers() -> list[Marker]:
    d = marker_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        sh = p.stem
        out.append(Marker.load(sh))
    return out


def _build_header_lines(config: Config) -> list[str]:
    """v0.3.7: 2줄로 분리 (mode + 설명 / refresh_interval + max_refresh)."""
    return [
        f"mode: {mode_label(config.mode, config)}",
        f"refresh_interval: {config.refresh_interval_minutes}m · max_refresh: {config.max_refresh_count}",
    ]


def _ns_to_dt(ns: int, now: datetime) -> datetime:
    """latest_fire 는 ns 단위 — datetime 으로 변환."""
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).astimezone()


def _build_session_box(marker: Marker, config: Config, now: datetime) -> list[str]:
    """현재 세션 박스 (TECH_SPEC §8 형식) — v0.3.5: sid/count/다음 발동 3개 줄만."""
    masked = mask_sid(marker.sid_hash)

    lines = [
        f"sid:             {masked}",
        f"repeat count:    {marker.wake_count} / {config.max_refresh_count}",
    ]
    # 다음 발동 예상: latest_fire + refresh_interval
    if marker.latest_fire > 0:
        next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
            minutes=config.refresh_interval_minutes
        )
        lines.append(
            f"다음 발동 예상:  {next_dt.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({_format_delta(next_dt, now)})"
        )

    return box_section("세션 (현재)", lines)


def _other_session_lines(marker: Marker, config: Config, now: datetime) -> list[str]:
    """다른 세션 inner 박스의 본문 — 다음 fire + 마지막 프롬프트."""
    lines = []
    if marker.latest_fire > 0:
        next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
            minutes=config.refresh_interval_minutes
        )
        lines.append(
            f"다음:    {next_dt.strftime('%H:%M:%S')} ({_format_delta(next_dt, now)})"
        )
    else:
        lines.append("다음:    —")
    prompt = marker.last_prompt if marker.last_prompt else "—"
    lines.append(f'마지막:  "{prompt}"')
    return lines


def _build_other_sessions_box(
    others: list[Marker], config: Config, now: datetime
) -> list[str]:
    """다른 세션 — outer "다른 세션" 박스 안에 sid 별 inner 박스 (v0.3.5).

    최대 OTHER_SESSIONS_MAX_SHOW 개 표시 (latest_fire 내림차순). 더 있으면 "... 외 N개" 표시.

    v0.3.6: latest_fire == 0 인 빈 marker 는 표시 제외 (다음 fire 시간 / 마지막
    프롬프트 모두 없는 빈 박스 노출 차단). on_user_prompt hook 만 발화 + Stop hook
    발화 전 chat 종료된 케이스 등.
    """
    active = [m for m in others if m.latest_fire > 0]
    if not active:
        return wrap_outer("다른 세션", ["없음"])

    sorted_others = sorted(active, key=lambda m: m.latest_fire, reverse=True)
    shown = sorted_others[:OTHER_SESSIONS_MAX_SHOW]

    # 모든 inner 박스의 너비 통일 — 각 박스의 자연 inner_width 의 최대값으로
    titles_and_lines = [(mask_sid(m.sid_hash), _other_session_lines(m, config, now)) for m in shown]
    natural_widths = []
    for title, lines in titles_and_lines:
        body_max = max(display_width(l) for l in lines) if lines else 0
        title_w = display_width(f"─ {title} ")
        natural_widths.append(max(body_max + 2, title_w + 2))
    target_inner = max(natural_widths)

    combined: list[str] = []
    for i, (title, lines) in enumerate(titles_and_lines):
        if i > 0:
            combined.append("")
        combined.extend(box_section(title, lines, min_width=target_inner))

    if len(sorted_others) > OTHER_SESSIONS_MAX_SHOW:
        combined.append("")
        combined.append(
            f"... 외 {len(sorted_others) - OTHER_SESSIONS_MAX_SHOW}개 (오래된 stale marker)"
        )

    return wrap_outer("다른 세션", combined)


def _read_json_safe(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _is_cn_plugin_enabled(data: dict) -> bool:
    """enabledPlugins 의 정확한 매칭: key 의 @ 앞부분이 'cache-necromancer'."""
    for key, val in data.get("enabledPlugins", {}).items():
        plugin_id = key.split("@", 1)[0]
        if plugin_id == "cache-necromancer" and val:
            return True
    return False


def _has_cn_stop_hook(data: dict) -> bool:
    for entry in data.get("hooks", {}).get("Stop", []):
        for h in entry.get("hooks", []):
            if CN_HOOK_MARKER in h.get("command", ""):
                return True
    return False


def _check_hook_registered() -> tuple[bool, str]:
    """plugin manifest 또는 settings.json/settings.local.json 의 hook 등록 detect."""
    claude_root = _resolve_claude_root()
    for fname in SETTINGS_FILES:
        data = _read_json_safe(claude_root / fname)
        if data is None:
            continue
        if _is_cn_plugin_enabled(data):
            return True, f"✅ plugin manifest ({fname} enabledPlugins)"
        if _has_cn_stop_hook(data):
            return True, f"✅ {fname} (수동 등록)"
    return (
        False,
        "❌ 미등록 — /plugin install cache-necromancer 후 새 chat 세션",
    )


def _check_deprecated_config() -> tuple[list[str], str | None]:
    """(폐기옵션 list, error_msg). lib.config 의 public API 사용 (중복 파싱 X)."""
    data, err = parse_config_file(_resolve_root() / "config.toml")
    if err:
        return [], err
    return detect_deprecated_keys(data), None


def _build_settings_box(config: Config) -> list[str]:
    registered, hook_status = _check_hook_registered()
    lines = [
        f"plugin: cache-necromancer v{_plugin_version()} ({'active' if registered else 'inactive'})",
        f"hook 등록: {hook_status}",
    ]
    deprecated, err = _check_deprecated_config()
    if err:
        lines.append(f"⚠️  config.toml 파싱 실패: {err} — 기본값 사용 중")
    elif deprecated:
        lines.append(f"⚠️  deprecated v0.2.x config: {', '.join(deprecated)} (무시됨)")
    else:
        lines.append("deprecated config: 없음")
    if config.mode == "notify":
        lines.append("⚠️  mode=notify — cache 갱신 효과 없음 (알림 only)")
    return box_section("설정 상태", lines)


def main() -> int:
    config_path = _resolve_root() / "config.toml"
    try:
        config = load_config(config_path)
    except ValueError as e:
        print(f"⚠️  config 로드 실패: {e}. 기본값 표시.", file=sys.stderr)
        config = Config()

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
        # marker 없음 — 빈 marker 로 표시
        current = Marker(sid_hash=current_hash, session_started_at=int(time.time()))

    body = [*_build_header_lines(config), ""]
    if current:
        body.extend(_build_session_box(current, config, now))
        body.append("")
    body.extend(_build_other_sessions_box(others, config, now))
    body.append("")
    body.extend(_build_settings_box(config))

    print("\n".join(wrap_outer("🔮 cache-necromancer 상태", body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

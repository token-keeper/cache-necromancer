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

from lib.box_renderer import box_section, wrap_outer  # noqa: E402
from lib.config import Config, detect_deprecated_keys, load_config, parse_config_file  # noqa: E402
from lib.marker import Marker, marker_dir, marker_path  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.mode_help import mode_label  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

CN_HOOK_MARKER = str(_PROJECT_ROOT / "scripts/refresh.py")
SETTINGS_FILES = ("settings.json", "settings.local.json")


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


def _build_header_line(config: Config) -> str:
    return (
        f"mode: {mode_label(config.mode, config)} · "
        f"refresh_interval: {config.refresh_interval_minutes}m · "
        f"max_refresh: {config.max_refresh_count}"
    )


def _ns_to_dt(ns: int, now: datetime) -> datetime:
    """latest_fire 는 ns 단위 — datetime 으로 변환."""
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).astimezone()


def _build_session_box(marker: Marker, config: Config, now: datetime) -> list[str]:
    """현재 세션 박스 (TECH_SPEC §8 형식)."""
    masked = mask_sid(marker.sid_hash)
    started = (
        datetime.fromtimestamp(marker.session_started_at, tz=timezone.utc).astimezone()
        if marker.session_started_at
        else None
    )

    lines = [f"sid:                {masked}"]
    if started:
        lines.append(f"시작:                {started.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(
        f"wake/notify count:  {marker.wake_count} / {config.max_refresh_count}"
    )
    lines.append(f"마지막 wake/notify: {_format_ts(marker.last_wake_at, now)}")

    # 다음 발동 예상: latest_fire + refresh_interval
    if marker.latest_fire > 0:
        next_dt = _ns_to_dt(marker.latest_fire, now) + timedelta(
            minutes=config.refresh_interval_minutes
        )
        lines.append(
            f"다음 발동 예상:     {next_dt.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({_format_delta(next_dt, now)})"
        )
        # cache 추정 만료: 1h cache 기준 fire + 60m
        cache_exp = _ns_to_dt(marker.latest_fire, now) + timedelta(hours=1)
        lines.append(
            f"cache 추정:         {cache_exp.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({_format_delta(cache_exp, now)})"
        )

    return box_section("세션 (현재)", lines)


def _build_other_sessions_box(others: list[Marker], config: Config, now: datetime) -> list[str]:
    if not others:
        return box_section("다른 세션", ["없음"])
    lines = []
    for m in others:
        masked = mask_sid(m.sid_hash)
        last = "—" if m.last_wake_at == 0 else _format_delta(
            datetime.fromtimestamp(m.last_wake_at, tz=timezone.utc).astimezone(), now
        )
        lines.append(
            f"{masked}  · wake/notify {m.wake_count}/{config.max_refresh_count} "
            f"· 마지막 {last}"
        )
    return box_section("다른 세션", lines)


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
        f"plugin: cache-necromancer v0.3.0 ({'active' if registered else 'inactive'})",
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

    body = [_build_header_line(config), ""]
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

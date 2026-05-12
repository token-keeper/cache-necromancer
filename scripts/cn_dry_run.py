#!/usr/bin/env python3
"""/cn:dry-run 백엔드 — 다음 fire 시점 시뮬레이션 (실제 호출 없음).

- 모든 추적 세션의 next_refresh_at, mode, cwd, 실제 호출될 명령어 표시
- disabled 세션은 disabled_reason 으로 표시 (fire 안 함)
- backoff_until / refresh_count / consecutive_fire_failures 같은 운영 정보 함께 표시
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import load_config  # noqa: E402
from lib.state import load_all_states, parse_iso  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


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


def _mode_label(mode: str, config) -> str:
    if mode == "notify":
        return "notify (알림만, 실제 fire 안 함)"
    if mode == "auto":
        return "auto (시점 도달 시 자동 fire)"
    if mode == "hybrid":
        return f"hybrid ({config.refresh.hybrid_wait_seconds}s 대기 후 fire)"
    return mode


def _format_active(s: dict, now: datetime, config) -> list[str]:
    sid = s.get("sid_hash", "?")
    lines = [f"  [{sid}]"]

    next_at = parse_iso(s.get("next_refresh_at"))
    if next_at is None:
        lines.append("      will fire at: — (next_refresh_at 미설정)")
    else:
        lines.append(
            f"      will fire at: {next_at.isoformat()} "
            f"({_format_delta(next_at, now)})"
        )

    lines.append(
        f"      mode:         {_mode_label(config.mode, config)}"
    )
    cmd = (
        f'claude -p "{config.refresh.prompt}" '
        f'--resume {s.get("session_id", "<sid>")} '
        f'--fork-session --no-session-persistence --output-format json'
    )
    lines.append(f"      command:      {cmd}")
    cwd = s.get("cwd")
    if cwd:
        lines.append(f"      cwd:          {cwd}")
    lines.append(
        f"      refresh_count: {s.get('refresh_count', 0)} / "
        f"{config.max_refresh_count}"
    )
    if s.get("backoff_until"):
        lines.append(f"      backoff_until: {s['backoff_until']}")
    if s.get("consecutive_fire_failures", 0) > 0:
        lines.append(
            f"      consec_fails:  {s['consecutive_fire_failures']}"
        )
    return lines


def _format_disabled(s: dict) -> list[str]:
    sid = s.get("sid_hash", "?")
    return [
        f"  [{sid}]  🛑 DISABLED",
        f"      reason:      {s.get('disabled_reason', '?')}",
        f"      disabled_at: {s.get('disabled_at', '?')}",
    ]


def main() -> int:
    root = _resolve_root()
    config_path = root / "config.toml"
    config = load_config(config_path)

    print("[dry-run] 추적 세션 fire 시뮬레이션 (실제 호출 없음)")
    print("─" * 30)

    sessions = load_all_states()
    if not sessions:
        print("추적 세션이 없습니다.")
        return 0

    now = datetime.now(timezone.utc)
    for s in sessions:
        print()
        formatter = _format_disabled if s.get("disabled") else _format_active
        for line in formatter(s, now, config) if not s.get("disabled") else formatter(s):
            print(line)

    print()
    print(f"설정: mode={config.mode}, max_refresh_count={config.max_refresh_count}")
    print(
        "mode를 'notify'로 바꾸면 fire 안 함 — "
        "~/.cache-necromancer/config.toml 편집."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

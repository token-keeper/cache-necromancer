#!/usr/bin/env python3
"""/cn:status 백엔드 — 추적 상태 표시.

- 데몬 alive 여부 (PID + 시작 시각)
- 추적 세션 목록 (active / disabled 구분)
- 현재 세션 (CLAUDE_CODE_SESSION_ID 기준) 에 (this) 표시
- 최근 24h fire log 통계 (Phase 2 이후 실제 데이터 채워짐)
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import load_config  # noqa: E402
from lib.lockfile import is_daemon_alive  # noqa: E402
from lib.session_id import sanitize  # noqa: E402
from lib.state import load_all_states, parse_iso  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def _current_sid_hash() -> str | None:
    """Bash tool 서브프로세스에 노출되는 CLAUDE_CODE_SESSION_ID 활용."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    try:
        return sanitize(sid)
    except ValueError:
        return None


def _format_delta(target: datetime, now: datetime) -> str:
    delta = (target - now).total_seconds()
    sign = ""
    if delta < 0:
        delta = -delta
        sign = "-"
    if delta < 60:
        return f"{sign}{int(delta)}s"
    m, s = divmod(int(delta), 60)
    if m < 60:
        return f"{sign}{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{sign}{h}h {m}m"


def _format_session(s: dict, now: datetime, current_sid: str | None) -> list[str]:
    sid_hash = s.get("sid_hash", "?")
    marker = " (this)" if current_sid and sid_hash == current_sid else ""
    disabled = s.get("disabled", False)

    lines: list[str] = []
    if disabled:
        lines.append(f"  {sid_hash}{marker}  🛑 DISABLED")
        lines.append(f"      reason:        {s.get('disabled_reason', '?')}")
        lines.append(f"      disabled_at:   {s.get('disabled_at', '?')}")
        return lines

    next_at = parse_iso(s.get("next_refresh_at"))
    last_fire = s.get("last_fire_at")
    last_reason = s.get("last_fire_reason")

    lines.append(f"  {sid_hash}{marker}")
    lines.append(f"      last_stop_at:  {s.get('last_stop_at', '—')}")
    if s.get("current_turn_started_at"):
        lines.append(
            f"      current_turn:  진행 중 (started {s['current_turn_started_at']})"
        )
    else:
        lines.append("      current_turn:  idle")
    if next_at is not None:
        lines.append(
            f"      next_refresh:  {next_at.isoformat()} ({_format_delta(next_at, now)})"
        )
    else:
        lines.append("      next_refresh:  —")
    lines.append(
        f"      refresh_count: {s.get('refresh_count', 0)}"
    )
    if last_fire:
        lines.append(
            f"      last_fire:     {last_fire} ({last_reason or 'ok'})"
        )
    failures = s.get("consecutive_fire_failures", 0)
    if failures > 0:
        lines.append(f"      consec_fails:  {failures}")
    if s.get("backoff_until"):
        lines.append(f"      backoff_until: {s['backoff_until']}")
    return lines


def _fire_stats_24h(root: Path, now: datetime) -> dict:
    """최근 24시간 fire.log 통계 (success / cache_cold / network_error 등)."""
    stats = {"total": 0, "by_reason": {}}
    cutoff = now - timedelta(hours=24)
    today_iso = date.today().isoformat()
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    for suffix in (today_iso, yesterday_iso):
        path = root / f"fire.log.{suffix}"
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
                # 형식: timestamp | fire | sid=... | reason=... | ...
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 5:
                    continue
                try:
                    ts = datetime.fromisoformat(parts[0])
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                stats["total"] += 1
                for p in parts:
                    if p.startswith("reason="):
                        reason = p[len("reason="):]
                        stats["by_reason"][reason] = stats["by_reason"].get(reason, 0) + 1
                        break
        except OSError:
            continue
    return stats


def main() -> int:
    root = _resolve_root()
    config_path = root / "config.toml"
    config = load_config(config_path)

    print("cache-necromancer 상태")
    print("─" * 30)

    lock_path = root / "daemon.lock"
    if is_daemon_alive(lock_path):
        try:
            meta = json.loads(lock_path.read_text())
            print(f"데몬: 살아있음 (PID {meta.get('pid')}, started {meta.get('started')})")
        except (json.JSONDecodeError, OSError):
            print("데몬: 살아있음 (메타 파싱 실패)")
    else:
        print("데몬: 종료됨 (다음 Stop hook이 spawn)")

    sessions = load_all_states()
    active = [s for s in sessions if not s.get("disabled")]
    disabled = [s for s in sessions if s.get("disabled")]
    print(f"추적 세션: {len(sessions)}개 (active {len(active)}, disabled {len(disabled)})")

    now = datetime.now(timezone.utc)
    current_sid = _current_sid_hash()

    for s in sessions:
        print()
        for line in _format_session(s, now, current_sid):
            print(line)

    print()
    stats = _fire_stats_24h(root, now)
    if stats["total"] == 0:
        print("최근 24h fire 통계: 없음")
    else:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(stats["by_reason"].items()))
        print(f"최근 24h fire 통계: {stats['total']}회 ({breakdown})")
    print(f"설정: mode={config.mode}, max_refresh_count={config.max_refresh_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

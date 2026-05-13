#!/usr/bin/env python3
"""/cn:status 백엔드 — 추적 상태 + 다음 fire 시뮬레이션 통합 출력 (v0.2.0).

섹션:
  ■ 데몬                 : alive/down + PID/started
  ■ 세션                 : sid 한 줄 요약 (next / refresh / idle/in-turn) + disabled
  ■ 다음 fire 시뮬레이션  : active 세션의 실제 호출될 command + cwd + last_fire
  ■ 최근 24h fires       : fire.log 통계

current_sid 와 sid_hash 가 일치하는 세션에는 (this) 마커.
"""
import json
import os
import shlex
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from daemon.refresh import build_fire_command  # noqa: E402
from lib.config import load_config  # noqa: E402
from lib.lockfile import is_daemon_alive  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.mode_help import mode_label  # noqa: E402
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
    sign = "-" if delta < 0 else ""
    delta = abs(delta)
    if delta < 60:
        return f"{sign}{int(delta)}s"
    m, s = divmod(int(delta), 60)
    if m < 60:
        return f"{sign}{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{sign}{h}h {m}m"


def _redact_command(cmd: list[str], sid_hash: str) -> str:
    """`--resume <full-id>` 의 full id를 마스킹해 출력 안전 보장."""
    redacted = list(cmd)
    try:
        idx = redacted.index("--resume")
    except ValueError:
        return shlex.join(redacted)
    if idx + 1 < len(redacted):
        redacted[idx + 1] = f"<sid:{mask_sid(sid_hash)}>"
    return shlex.join(redacted)


def _trunc_microseconds(ts: str | None) -> str:
    """ISO timestamp 의 마이크로초 절단. 파싱 실패 시 원본 반환."""
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts).replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        return ts


def _print_daemon(lock_path: Path) -> None:
    print("■ 데몬")
    if is_daemon_alive(lock_path):
        try:
            meta = json.loads(lock_path.read_text())
            print(f"  살아있음 (PID {meta.get('pid')}, started {meta.get('started')})")
        except (json.JSONDecodeError, OSError):
            print("  살아있음 (메타 파싱 실패)")
    else:
        print("  종료됨 — 다음 Stop hook 이 spawn")


def _format_active_summary(
    s: dict, now: datetime, current_sid: str | None, config
) -> list[str]:
    """active 세션 한 줄 요약 + warning 펼침."""
    sid_hash = s.get("sid_hash", "?")
    masked = mask_sid(sid_hash)
    marker = " (this)" if current_sid and sid_hash == current_sid else ""

    next_at = parse_iso(s.get("next_refresh_at"))
    next_str = (
        f"next {_format_delta(next_at, now)}"
        if next_at is not None
        else "next —"
    )
    refresh_count = s.get("refresh_count", 0)
    turn = "in turn" if s.get("current_turn_started_at") else "idle"

    lines = [
        f"  [{masked}]{marker}  {next_str} · "
        f"refresh {refresh_count}/{config.max_refresh_count} · {turn}"
    ]

    warnings = []
    if s.get("consecutive_fire_failures", 0) > 0:
        warnings.append(f"⚠️ {s['consecutive_fire_failures']} consec fails")
    if s.get("backoff_until"):
        warnings.append(f"backoff until {s['backoff_until']}")
    if warnings:
        lines.append(f"      {' · '.join(warnings)}")
    return lines


def _format_disabled_summary(s: dict) -> str:
    sid_hash = s.get("sid_hash", "?")
    masked = mask_sid(sid_hash)
    reason = s.get("disabled_reason", "?")
    at = _trunc_microseconds(s.get("disabled_at"))
    return f"  [{masked}]  🛑 DISABLED ({reason}, {at})"


def _print_sessions(
    active: list[dict],
    disabled: list[dict],
    now: datetime,
    current_sid: str | None,
    config,
) -> None:
    print(f"■ 세션 (active {len(active)}, disabled {len(disabled)})")
    if not active and not disabled:
        print("  추적 중인 세션 없음")
        return
    for s in active:
        for line in _format_active_summary(s, now, current_sid, config):
            print(line)
    for s in disabled:
        print(_format_disabled_summary(s))


def _print_next_fires(active: list[dict], config) -> None:
    print("■ 다음 fire 시뮬레이션 (active 세션)")
    if not active:
        print("  active 세션 없음")
        return
    for s in active:
        sid_hash = s.get("sid_hash", "?")
        masked = mask_sid(sid_hash)
        argv = build_fire_command(s, config)
        print(f"  [{masked}]")
        print(f"      command:   {_redact_command(argv, sid_hash)}")
        cwd = s.get("cwd")
        if cwd:
            print(f"      cwd:       {cwd}")
        last_fire = s.get("last_fire_at")
        if last_fire:
            reason = s.get("last_fire_reason") or "ok"
            print(f"      last_fire: {last_fire} ({reason})")


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


def _print_fire_stats(root: Path, now: datetime) -> None:
    print("■ 최근 24h fires")
    stats = _fire_stats_24h(root, now)
    if stats["total"] == 0:
        print("  없음")
    else:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(stats["by_reason"].items()))
        print(f"  총 {stats['total']}회 ({breakdown})")


def main() -> int:
    root = _resolve_root()
    config_path = root / "config.toml"
    config = load_config(config_path)

    print("cache-necromancer 상태")
    print("─" * 32)

    _print_daemon(root / "daemon.lock")
    print()

    sessions = load_all_states()
    active = [s for s in sessions if not s.get("disabled")]
    disabled = [s for s in sessions if s.get("disabled")]
    now = datetime.now(timezone.utc)
    current_sid = _current_sid_hash()

    _print_sessions(active, disabled, now, current_sid, config)
    print()

    _print_next_fires(active, config)
    print()

    _print_fire_stats(root, now)
    print()

    print(f"모드: {mode_label(config.mode, config)} · max_refresh: {config.max_refresh_count}")
    print("설정 변경 / 모드 비교: /cn:config")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""/cn:status 백엔드 — 추적 상태 + 다음 fire 시뮬레이션 통합 출력 (v0.2.0).

박스 표 형식:
  ┌─ 데몬 ─┐                  alive/down + PID/started
  ┌─ 세션 ─┐                  sid · 상태 · next · refresh · warning (표)
  ┌─ 다음 fire 시뮬레이션 ─┐  active 세션의 command + cwd + last_fire
  ┌─ 최근 24h fires ─┐        fire.log 통계

current_sid 와 sid_hash 가 일치하는 세션은 sid 뒤에 `*` 마커.
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

from lib.box_renderer import box_section, box_table, display_width, wrap_outer  # noqa: E402
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
    """Bash tool 서브프로세스 / hook subprocess 에 노출되는 CLAUDE_CODE_SESSION_ID."""
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


def _trunc_microseconds(ts: str | None) -> str:
    """ISO timestamp 의 마이크로초 절단. 파싱 실패 시 원본 반환."""
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts).replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        return ts


def _short_time(ts: str | None) -> str:
    """ISO timestamp 에서 HH:MM:SS 만 추출. 박스 표 컬럼 너비 절약용."""
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts


def _build_daemon_box(lock_path: Path, min_width: int = 0) -> list[str]:
    if is_daemon_alive(lock_path):
        try:
            meta = json.loads(lock_path.read_text())
            line = f"✅ 살아있음 · PID {meta.get('pid')} · 시작 {meta.get('started')}"
        except (json.JSONDecodeError, OSError):
            line = "✅ 살아있음 (메타 파싱 실패)"
    else:
        line = "❌ 종료됨 — 다음 Stop hook 이 spawn"
    return box_section("데몬", [line], min_width=min_width)


def _active_row(s: dict, now: datetime, current_sid: str | None, config) -> list[str]:
    sid_hash = s.get("sid_hash", "?")
    masked = mask_sid(sid_hash)
    marker = "*" if current_sid and sid_hash == current_sid else ""

    next_at = parse_iso(s.get("next_refresh_at"))
    next_str = _format_delta(next_at, now) if next_at is not None else "—"

    refresh_count = s.get("refresh_count", 0)
    refresh_str = f"{refresh_count}/{config.max_refresh_count}"
    turn = "in turn" if s.get("current_turn_started_at") else "idle"

    warnings = []
    if s.get("consecutive_fire_failures", 0) > 0:
        warnings.append(f"⚠️ {s['consecutive_fire_failures']} fails")
    if s.get("backoff_until"):
        warnings.append(f"backoff {_short_time(s['backoff_until'])}")
    warning_str = " · ".join(warnings) if warnings else "—"

    return [masked + marker, turn, next_str, refresh_str, _truncate(warning_str, 40)]


def _disabled_row(s: dict) -> list[str]:
    sid_hash = s.get("sid_hash", "?")
    masked = mask_sid(sid_hash)
    # consecutive_failures_* prefix 는 공통이라 단축
    reason = s.get("disabled_reason", "?").replace("consecutive_failures_", "")
    at = _short_time(s.get("disabled_at"))
    return [masked, "🛑 DISABLED", "—", "—", _truncate(f"{reason} ({at})", 40)]


def _build_sessions_box(
    active: list[dict],
    disabled: list[dict],
    now: datetime,
    current_sid: str | None,
    config,
    min_width: int = 0,
) -> list[str]:
    title = f"세션 (active {len(active)}, disabled {len(disabled)})"
    if not active and not disabled:
        return box_section(title, ["추적 중인 세션 없음"], min_width=min_width)

    headers = ["sid", "상태", "next", "refresh", "warning"]
    rows = [_active_row(s, now, current_sid, config) for s in active]
    rows += [_disabled_row(s) for s in disabled]
    return box_table(title, headers, rows, min_width=min_width, row_separator=True)


def _truncate(s: str, max_width: int) -> str:
    """display_width 기준 truncate — 한글/이모지가 두 셀 차지하는 케이스 정확 처리."""
    if display_width(s) <= max_width:
        return s
    out = ""
    for c in s:
        if display_width(out + c) > max_width - 3:
            break
        out += c
    return out + "..."


def _build_next_fires_box(active: list[dict], config, min_width: int = 0) -> list[str]:
    title = "active 세션 디테일"
    if not active:
        return box_section(title, ["active 세션 없음"], min_width=min_width)

    lines = []
    for i, s in enumerate(active):
        if i > 0:
            lines.append("")
        sid_hash = s.get("sid_hash", "?")
        masked = mask_sid(sid_hash)
        lines.append(masked)

        cwd = s.get("cwd")
        if cwd:
            lines.append(f"  cwd:          {_truncate(cwd, 70)}")

        last_prompt = s.get("last_user_prompt_excerpt")
        if last_prompt:
            lines.append(f"  last prompt:  {last_prompt}")

        last_fire = s.get("last_fire_at")
        if last_fire:
            reason = s.get("last_fire_reason") or "ok"
            lines.append(f"  last fire:    {last_fire} ({reason})")
    return box_section(title, lines, min_width=min_width)


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


def _build_fire_stats_box(root: Path, now: datetime, min_width: int = 0) -> list[str]:
    stats = _fire_stats_24h(root, now)
    if stats["total"] == 0:
        line = "없음"
    else:
        breakdown = " · ".join(f"{k}={v}" for k, v in sorted(stats["by_reason"].items()))
        line = f"총 {stats['total']}회 · {breakdown}"
    return box_section("최근 24h fires", [line], min_width=min_width)


def main() -> int:
    root = _resolve_root()
    config_path = root / "config.toml"
    config = load_config(config_path)

    sessions = load_all_states()
    active = [s for s in sessions if not s.get("disabled")]
    disabled = [s for s in sessions if s.get("disabled")]
    now = datetime.now(timezone.utc)
    current_sid = _current_sid_hash()

    notice_lines = [
        f"모드: {mode_label(config.mode, config)} · max_refresh: {config.max_refresh_count}",
        "설정 변경 / 모드 비교: /cn:config",
    ]

    # outer 박스를 max_width 로 고정. inner_max = max_width - 4 (outer "│ ... │" padding).
    # CN_MAX_WIDTH 환경변수 우선, 기본 100.
    max_width = int(os.environ.get("CN_MAX_WIDTH", "100"))
    inner_max = max(40, max_width - 4)
    inner_boxes = [
        _build_daemon_box(root / "daemon.lock", min_width=inner_max),
        _build_sessions_box(active, disabled, now, current_sid, config, min_width=inner_max),
        _build_next_fires_box(active, config, min_width=inner_max),
        _build_fire_stats_box(root, now, min_width=inner_max),
    ]
    # 헤더 바로 아래에 안내 줄 → 빈 줄 → inner 박스들
    body: list[str] = list(notice_lines)
    for box in inner_boxes:
        body.append("")
        body.extend(box)

    print("\n".join(wrap_outer("🔮 cache-necromancer 상태", body, min_width=max_width - 2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

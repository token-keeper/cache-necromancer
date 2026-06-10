#!/usr/bin/env python3
"""Stop hook 의 asyncRewake 본체 (TECH_SPEC §4, v0.5.0 arm/예산 분기).

Claude Code 의 Stop hook 에 등록되어 background 에서 실행됨:
  1. marker 의 latest_fire 갱신 (timestamp 비교용)
  2. arm=="always" 일 때만 진입부 max_refresh_count 체크 (skip)
  3. config.refresh_interval_minutes 분 sleep
  4. sleep 후 latest_fire 재확인 — 더 최근 fire 가 있으면 skip
  5. arm/예산 분기:
     - arm=manual + set_budget_remaining==0 (not eligible):
         notify.enabled=true  → 알림 1회 + exit 0 (wake X, 연쇄 fire X)
         notify.enabled=false → no-op exit 0
     - eligible (arm=always 또는 budget>0):
         notify.enabled=true  → 알림 + grace_seconds sleep + 재확인 + exit 2
         notify.enabled=false → 즉시 exit 2
     - wake 시 manual 은 예산 차감 후 (consumed/total) ping,
                always 는 (wake_count/max_refresh_count) ping.

PRD 불변: 어떤 실패도 chat 동작 차단 X (best-effort).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import Config, ensure_config_file, load_config  # noqa: E402
from lib.install_version import is_latest_install  # noqa: E402
from lib.logger import log_info, log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.mask import mask_sid  # noqa: E402
from lib.notify import notify  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

PING_PREFIX = "[cn:keepalive"


def _build_ping(nm: str) -> str:
    """동적 PING 메시지 — local 시각 + 'N/M' 카운트 포함.

    nm: 호출자가 조립한 "consumed/total" (manual) 또는 "count/max" (always).
    응답 형식도 'ok @HH:MM (N/M)' 으로 강제해서 chat history 만 봐도
    언제 몇 번째 wake 였는지 확인 가능.
    """
    hhmm = datetime.now().strftime("%H:%M")
    return (
        f"{PING_PREFIX} {hhmm}, {nm}] "
        f"reply with exactly 'ok @{hhmm} ({nm})'. "
        "No tools, no analysis. Use minimal output tokens."
    )


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


_BUDDY_PATTERN = re.compile(
    r"cache-necromancer/([0-9.]+)/scripts/refresh\.py"
)


def _kill_older_buddies() -> None:
    """자기보다 옛날 버전의 refresh.py 잔존 process 를 SIGTERM.

    plugin 업데이트 직전에 spawn 되어 sleep 중인 옛날 코드의 refresh.py 들이
    깨어나 옛날 포맷 알림을 발사하는 것을 차단. is_latest_install() 통과 후
    호출되어 자기가 latest 임이 보장된 상태에서만 동작. pgrep 미설치 /
    SIGTERM 실패 / parse 오류 모두 silent.
    """
    parts = _HERE.parent.name.split(".")
    try:
        my_version = tuple(int(p) for p in parts)
    except ValueError:
        return
    my_pid = os.getpid()
    try:
        result = subprocess.run(
            ["pgrep", "-laf", "cache-necromancer/.*/scripts/refresh.py"],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return
    for line in (result.stdout or "").splitlines():
        m = _BUDDY_PATTERN.search(line)
        if not m:
            continue
        try:
            pid = int(line.split(None, 1)[0])
            ver = tuple(int(x) for x in m.group(1).split("."))
        except (ValueError, IndexError):
            continue
        if pid == my_pid or ver >= my_version:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            log_info(
                f"[refresh] killed older buddy pid={pid} "
                f"version={'.'.join(map(str, ver))}"
            )
        except OSError:
            pass


def _resolve_session_id() -> str:
    """stdin JSON ({"session_id": ...}) 우선, env fallback.

    Claude Code hook 은 stdin 으로 JSON payload 전달 (CLAUDE_CODE_SESSION_ID
    환경변수는 보장 X). on_user_prompt.py / on_session_end.py 와 일관.
    """
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            sid = data.get("session_id", "")
            if sid:
                return sid
    except (json.JSONDecodeError, OSError):
        pass
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


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


def _notify_session(
    message: str, marker: Marker, config: Config, count_for_display: int
) -> None:
    """세션 식별 정보를 채워 알림 발송.

    여러 세션이 동시에 실행 중일 때 어느 프로젝트의 알림인지 구분할 수 있게:
      - title:    cache-necromancer · <basename(cwd)>
      - subtitle: <sid8> · (N/M)
      - body:     <단축경로> — <message>
    cwd 가 없으면 title/body 의 cwd 부분을 생략.
    """
    base_title = "cache-necromancer"
    if marker.cwd:
        basename = os.path.basename(marker.cwd.rstrip("/")) or marker.cwd
        title = f"{base_title} · {basename}"
    else:
        title = base_title

    subtitle = (
        f"{mask_sid(marker.sid_hash)} · "
        f"({count_for_display}/{config.max_refresh_count})"
    )

    abbrev = _abbrev_home(marker.cwd)
    body = f"{abbrev} — {message}" if abbrev else message
    notify(body, title=title, subtitle=subtitle)


def _save_marker(marker: Marker, context: str) -> bool:
    """save 시도 + graceful degradation. 실패 시 False (호출자가 abort)."""
    try:
        marker.save()
        return True
    except OSError as e:
        log_warn(f"[refresh] marker save 실패 ({context}): {type(e).__name__}: {e}")
        return False


def _do_wake(marker: Marker, sid_hash: str, config: Config) -> int:
    """wake_count/예산 갱신 + save 후 stderr ping + exit 2.

    manual(예산 소비) 이면 ping 은 (consumed/total), always 는 (count/max).
    save 실패 시 wake 자체는 진행 (cache 갱신 우선, count 누락 허용).
    """
    marker.wake_count += 1
    marker.last_wake_at = int(time.time())
    if marker.set_budget_remaining > 0:
        consumed = marker.set_budget_total - marker.set_budget_remaining + 1
        marker.set_budget_remaining -= 1
        nm = f"{consumed}/{marker.set_budget_total}"
    else:
        nm = f"{marker.wake_count}/{config.max_refresh_count}"
    _save_marker(marker, "wake")
    log_info(f"[refresh] wake sid={sid_hash} count={marker.wake_count} nm={nm}")
    print(_build_ping(nm), file=sys.stderr)
    return 2


def _do_notify(marker: Marker, sid_hash: str, config: Config, message: str) -> int:
    """notify 시에만 count 증가 — 사용자에게 실제 도달한 시도.

    notify.enabled=false 면 알림도 안 가고 wake 도 안 하니 사실상 no-op.
    count 도 증가시키지 않음 (count 의미: 사용자에게 실제로 도달한 시도).
    """
    if not config.notify.enabled:
        log_info(f"[refresh] notify 대상인데 notify.enabled=false, no-op sid={sid_hash}")
        return 0
    marker.wake_count += 1
    marker.last_wake_at = int(time.time())
    _save_marker(marker, "notify")
    _notify_session(message, marker, config, marker.wake_count)
    log_info(f"[refresh] notify sid={sid_hash} count={marker.wake_count}")
    return 0


def main() -> int:
    if not is_latest_install():
        return 0
    _kill_older_buddies()
    sid = _resolve_session_id()
    if not sid:
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0

    config_path = _resolve_root() / "config.toml"
    # 첫 hook fire 시 자동 생성 (PRD §3.2 / TECH_SPEC §3.2)
    try:
        ensure_config_file(config_path)
    except OSError as e:
        log_warn(f"[refresh] config.toml 자동 생성 실패: {e}")
    try:
        config = load_config(config_path)
    except ValueError as e:
        log_warn(f"[refresh] config 로드 실패: {e}")
        return 0

    # 진입부: latest_fire 갱신 + max_refresh_count 체크
    # my_ts 를 ns 단위로 — 같은 초 안에 fire 2개 발생해도 latest_fire 비교 정확
    marker = Marker.load(sid_hash)
    my_ts = time.time_ns()
    marker.latest_fire = my_ts
    if not _save_marker(marker, "fire"):
        return 0

    if config.wake.arm == "always" and marker.wake_count >= config.max_refresh_count:
        log_info(
            f"[refresh] max_refresh_count {config.max_refresh_count} 도달, skip "
            f"sid={sid_hash}"
        )
        return 0

    # sleep — cache TTL 만료 직전까지
    time.sleep(config.refresh_interval_minutes * 60)

    # sleep 후 marker 재 load — 더 최근 fire 또는 user activity 가 있으면 skip
    marker = Marker.load(sid_hash)
    # latest_fire == 0 = SessionEnd 가 마커 파일을 삭제해서 Marker.load 가
    # fresh marker 를 반환한 경우. 이미 종료된 세션의 좀비 wake/notify 방지 +
    # 좀비 마커 재생성 방지. (refresh.py 진입부에 my_ts 로 저장했으므로 정상
    # 흐름에서는 0 이 될 수 없음.)
    if marker.latest_fire == 0:
        log_info(f"[refresh] marker 사라짐 (SessionEnd 후), skip sid={sid_hash}")
        return 0
    if marker.latest_fire > my_ts:
        log_info(
            f"[refresh] superseded (newer fire={marker.latest_fire} > "
            f"my_ts={my_ts}), skip"
        )
        return 0
    # 사용자가 sleep 동안 활발히 prompt 를 쳤다면 wake/notify 하지 않는다.
    # model 응답이 50분 넘게 진행되어 새 Stop hook fire 가 안 들어와도
    # last_user_activity_at_ns 가 갱신되어 있어서 가드됨.
    if marker.last_user_activity_at_ns > my_ts:
        log_info(
            f"[refresh] superseded by user activity "
            f"(last_user_activity_at_ns={marker.last_user_activity_at_ns} > "
            f"my_ts={my_ts}), skip"
        )
        return 0

    # arm/예산 분기 (spec §7)
    eligible = config.wake.arm == "always" or marker.set_budget_remaining > 0

    if not eligible:
        # 알림만 — wake 없음 → 연쇄 fire 없음 → 자리비움당 알림 최대 1회
        return _do_notify(
            marker, sid_hash, config,
            "cache 만료 임박 — /cn:set N 으로 연장 가능",
        )

    if config.notify.enabled:
        # wake 가 일어나면 _do_wake 에서 count 가 오르므로 +1 한 값을 표시
        _notify_session(
            f"{config.wake.grace_seconds}초 후 자동 wake — 직접 input 시 취소",
            marker, config, marker.wake_count + 1,
        )
        time.sleep(config.wake.grace_seconds)
        marker = Marker.load(sid_hash)
        if marker.latest_fire == 0:
            log_info(f"[refresh] grace 중 SessionEnd, wake 취소 sid={sid_hash}")
            return 0
        if marker.latest_fire > my_ts:
            log_info(f"[refresh] grace 중 user input — wake 취소 sid={sid_hash}")
            return 0
        if marker.last_user_activity_at_ns > my_ts:
            log_info(f"[refresh] grace 중 user activity — wake 취소 sid={sid_hash}")
            return 0
        if config.wake.arm != "always" and marker.set_budget_remaining <= 0:
            log_info(f"[refresh] grace 중 예산 소멸 — wake 취소 sid={sid_hash}")
            return 0

    return _do_wake(marker, sid_hash, config)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Stop hook 의 asyncRewake 본체 (TECH_SPEC §4).

Claude Code 의 Stop hook 에 등록되어 background 에서 실행됨:
  1. marker 의 latest_fire 갱신 (timestamp 비교용)
  2. wake_count 가 max_refresh_count 도달 시 skip
  3. config.refresh_interval_minutes 분 sleep
  4. sleep 후 latest_fire 재확인 — 더 최근 fire 가 있으면 skip
  5. mode 별 분기:
     - notify: osascript 알림 + exit 0 (wake X)
     - auto: stderr ping + exit 2 (Claude Code 가 chat 세션 wake)
     - hybrid: 알림 + hybrid_wait 추가 sleep + 재확인 + exit 2

PRD 불변: 어떤 실패도 chat 동작 차단 X (best-effort).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import Config, ensure_config_file, load_config  # noqa: E402
from lib.logger import log_info, log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.notify import notify  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

PING_PREFIX = "[cn:keepalive"


def _build_ping(wake_count: int, max_count: int) -> str:
    """동적 PING 메시지 — local 시각 + 'N/M' wake 카운트 포함.

    응답 형식도 'ok @HH:MM (N/M)' 으로 강제해서 chat history 만 봐도
    언제 몇 번째 wake 였는지 확인 가능.
    """
    hhmm = datetime.now().strftime("%H:%M")
    nm = f"{wake_count}/{max_count}"
    return (
        f"{PING_PREFIX} {hhmm}, {nm}] "
        f"reply with exactly 'ok @{hhmm} ({nm})'. "
        "No tools, no analysis. Use minimal output tokens."
    )


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


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


def _save_marker(marker: Marker, context: str) -> bool:
    """save 시도 + graceful degradation. 실패 시 False (호출자가 abort)."""
    try:
        marker.save()
        return True
    except OSError as e:
        log_warn(f"[refresh] marker save 실패 ({context}): {type(e).__name__}: {e}")
        return False


def _do_wake(marker: Marker, sid_hash: str, config: Config) -> int:
    """wake_count 증가 + last_wake_at 갱신 + stderr ping + exit 2.

    save 실패 시 wake 자체는 진행 (cache 갱신 우선, count 누락 허용).
    """
    marker.wake_count += 1
    marker.last_wake_at = int(time.time())
    _save_marker(marker, "wake")
    log_info(f"[refresh] wake sid={sid_hash} count={marker.wake_count}")
    print(_build_ping(marker.wake_count, config.max_refresh_count), file=sys.stderr)
    return 2


def _do_notify(marker: Marker, sid_hash: str, config: Config) -> int:
    """notify mode — 알림 발송 시에만 count 증가.

    system_notification=false 면 알림도 안 가고 wake 도 안 하니 사실상 no-op.
    count 도 증가시키지 않음 (count 의미: 사용자에게 실제로 도달한 시도).
    """
    if not config.notify.system_notification:
        log_info(f"[refresh] notify mode 인데 system_notification=false, no-op sid={sid_hash}")
        return 0
    marker.wake_count += 1
    marker.last_wake_at = int(time.time())
    _save_marker(marker, "notify")
    notify("cache 만료 임박, 직접 chat 으로 돌아오세요")
    log_info(f"[refresh] notify sid={sid_hash} count={marker.wake_count}")
    return 0


def main() -> int:
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

    if marker.wake_count >= config.max_refresh_count:
        log_info(
            f"[refresh] max_refresh_count {config.max_refresh_count} 도달, skip "
            f"sid={sid_hash}"
        )
        return 0

    # sleep — cache TTL 만료 직전까지
    time.sleep(config.refresh_interval_minutes * 60)

    # sleep 후 marker 재 load — 더 최근 fire 가 있으면 skip
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

    # mode 별 분기
    if config.mode == "notify":
        return _do_notify(marker, sid_hash, config)

    if config.mode == "hybrid":
        if config.notify.system_notification:
            notify(
                f"{config.refresh.hybrid_wait_seconds}초 후 자동 wake — "
                "직접 input 시 취소"
            )
        time.sleep(config.refresh.hybrid_wait_seconds)
        marker = Marker.load(sid_hash)
        if marker.latest_fire == 0:
            log_info(
                f"[refresh] hybrid wait 중 SessionEnd, wake 취소 sid={sid_hash}"
            )
            return 0
        if marker.latest_fire > my_ts:
            log_info(
                "[refresh] hybrid wait 중 user input — wake 취소 sid="
                f"{sid_hash}"
            )
            return 0

    # auto 또는 hybrid 통과 → wake
    return _do_wake(marker, sid_hash, config)


if __name__ == "__main__":
    sys.exit(main())

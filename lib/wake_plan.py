"""깨우기 판정 공통 규칙 (v0.12.0) — refresh·cn_set·cn_status 가 공유.

- 자리비움마다 자동으로 최대 `auto_wakes` 회 깨운다.
- `/cn:set N` 은 이번 자리비움만 N회로 덮어쓴다 (덮어쓰기 중엔 자동 몫 없음).
- `/cn:set 0`·`off` 는 세션 끝까지 끈다.

mod(hooks/register.tsx)의 띠 생존 시각도 같은 식: base + remaining × interval + ttl.
"""
from lib.config import Config
from lib.marker import Marker

_MIN_NS = 60 * 1_000_000_000


def wake_mode(m: Marker) -> str:
    """"off"(/cn:set 0·off) · "set"(/cn:set N 덮어쓰기) · "auto"."""
    if m.wake_off:
        return "off"
    if m.set_budget_total > 0:
        return "set"
    return "auto"


def remaining_wakes(m: Marker, c: Config) -> int:
    """이번 자리비움에 남은 깨우기 횟수."""
    mode = wake_mode(m)
    if mode == "off":
        return 0
    if mode == "set":
        return max(0, m.set_budget_remaining)
    return max(0, c.auto_wakes - m.wake_count)


def can_wake(c: Config) -> bool:
    """interval ≥ ttl 이면 깨우기 전에 캐시가 죽는다 — mod 도 깨우지 않는다."""
    return c.refresh_interval_minutes < c.cache_ttl_minutes


def cache_expired(latest_fire_ns: int, now_ns: int, c: Config) -> bool:
    """마지막 Stop 뒤 ttl 이 지났다 — 지금 캐시는 이미 죽었고 깨우기 창도 지났다."""
    return latest_fire_ns > 0 and now_ns >= latest_fire_ns + c.cache_ttl_minutes * _MIN_NS


def survive_until_ns(anchor_ns: int, remaining: int, c: Config) -> int:
    """캐시 최대 생존 시각 (ns). anchor = 캐시 기준 시각 (Python 은 latest_fire, 0 이면 now).

    깨울 수 없는 설정(interval ≥ ttl)이면 남은 횟수를 세지 않는다.
    """
    if not can_wake(c):
        remaining = 0
    return anchor_ns + (remaining * c.refresh_interval_minutes + c.cache_ttl_minutes) * _MIN_NS

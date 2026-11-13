"""Tests for lib/wake_plan.py — 깨우기 판정 공통 규칙 (v0.12.0)."""
from lib.config import Config
from lib.marker import Marker
from lib.wake_plan import cache_expired, can_wake, remaining_wakes, survive_until_ns, wake_mode

MIN_NS = 60 * 1_000_000_000


def _m(**kw) -> Marker:
    return Marker(sid_hash="x", **kw)


def test_auto_remaining():
    c = Config(auto_wakes=2)
    assert remaining_wakes(_m(), c) == 2
    assert remaining_wakes(_m(wake_count=1), c) == 1
    assert remaining_wakes(_m(wake_count=5), c) == 0   # 음수 없음
    assert wake_mode(_m()) == "auto"


def test_override_has_no_auto_share():
    c = Config(auto_wakes=5)
    m = _m(wake_count=1, set_budget_remaining=0, set_budget_total=1)
    assert wake_mode(m) == "set"
    assert remaining_wakes(m, c) == 0
    assert remaining_wakes(_m(wake_count=9, set_budget_remaining=3, set_budget_total=3), c) == 3


def test_wake_off_wins():
    m = _m(wake_off=True, set_budget_remaining=3, set_budget_total=3)
    assert wake_mode(m) == "off"
    assert remaining_wakes(m, Config()) == 0


def test_survive_formula():
    """anchor + remaining × interval + ttl (grace 없음) — mod 띠와 같은 식."""
    c = Config(refresh_interval_minutes=50, cache_ttl_minutes=60)
    assert survive_until_ns(1_000, 0, c) == 1_000 + 60 * MIN_NS
    assert survive_until_ns(1_000, 2, c) == 1_000 + (2 * 50 + 60) * MIN_NS
    assert isinstance(survive_until_ns(1_000, 2, c), int)


def test_interval_ge_ttl_ignores_remaining():
    """interval ≥ ttl 이면 깨우기 전에 캐시가 죽는다 — 남은 횟수를 생존에 안 쓴다."""
    c = Config(refresh_interval_minutes=60, cache_ttl_minutes=60)
    assert not can_wake(c)
    assert survive_until_ns(1_000, 3, c) == 1_000 + 60 * MIN_NS


def test_cache_expired():
    c = Config(cache_ttl_minutes=60)
    assert not cache_expired(0, 10**18, c)                     # Stop 없음 → 판단 안 함
    assert not cache_expired(1_000, 1_000 + 59 * MIN_NS, c)
    assert cache_expired(1_000, 1_000 + 60 * MIN_NS, c)

"""sleep/wake 감지 — time.monotonic 단독 기반.

폴링 데몬이 ``time.sleep(N)`` 호출 직전 ``mark_sleep_start(N)`` 으로 등록하고,
sleep 직후 ``detect_after_sleep()`` 를 호출하면 "expected sleep vs actual
monotonic elapsed" 차이가 threshold를 넘는 경우 drift 초 단위로 반환한다.

wall clock (``datetime.now()``) 은 DST / NTP step 영향을 받아 drift 계산에
사용하지 않는다 (감지에서만 사용 안 함; 로깅은 호출자가 별도로 처리).
"""
import time
from typing import Optional


class DriftDetector:
    """sleep/wake 감지기.

    데몬 부팅 직후 첫 ``mark_sleep_start()`` 이전엔 평가 기준점이 없어
    ``detect_after_sleep()`` 가 0 반환 (false positive 방지).
    """

    def __init__(self, threshold_seconds: int = 30) -> None:
        self.threshold = threshold_seconds
        self.last_mono: Optional[float] = None
        self.last_expected_sleep: float = 0.0

    def mark_sleep_start(self, expected_seconds: float) -> None:
        """``time.sleep(expected_seconds)`` 호출 직전에 등록."""
        self.last_mono = time.monotonic()
        self.last_expected_sleep = expected_seconds

    def detect_after_sleep(self) -> int:
        """sleep 직후 호출. drift 초 (threshold 미만이면 0)."""
        if self.last_mono is None:
            return 0
        actual = time.monotonic() - self.last_mono
        drift = actual - self.last_expected_sleep
        if drift > self.threshold:
            return int(drift)
        return 0

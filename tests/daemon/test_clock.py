"""Tests for daemon.clock.DriftDetector"""
from unittest.mock import patch


def test_detect_before_first_mark_returns_zero():
    """첫 mark_sleep_start 이전엔 평가 기준점이 없어 0 반환."""
    from daemon.clock import DriftDetector

    d = DriftDetector(threshold_seconds=30)
    assert d.detect_after_sleep() == 0


def test_normal_sleep_no_drift():
    from daemon.clock import DriftDetector

    d = DriftDetector(threshold_seconds=30)
    with patch("daemon.clock.time.monotonic") as mock_mono:
        mock_mono.return_value = 100.0
        d.mark_sleep_start(60.0)
        # 정상 sleep 후 60초 흐름
        mock_mono.return_value = 160.0
        drift = d.detect_after_sleep()
        assert drift == 0


def test_sleep_wake_drift_detected():
    """expected 60s인데 실제 1200s 흐름 → 1140s drift."""
    from daemon.clock import DriftDetector

    d = DriftDetector(threshold_seconds=30)
    with patch("daemon.clock.time.monotonic") as mock_mono:
        mock_mono.return_value = 100.0
        d.mark_sleep_start(60.0)
        mock_mono.return_value = 1300.0  # 1200s 흐름
        drift = d.detect_after_sleep()
        assert drift > 30
        assert drift == 1140


def test_drift_below_threshold_not_reported():
    """threshold 미만 drift는 0 반환 (정상 sleep 변동)."""
    from daemon.clock import DriftDetector

    d = DriftDetector(threshold_seconds=30)
    with patch("daemon.clock.time.monotonic") as mock_mono:
        mock_mono.return_value = 100.0
        d.mark_sleep_start(60.0)
        # 60 + 10s 추가 = threshold 30 미만
        mock_mono.return_value = 170.0
        drift = d.detect_after_sleep()
        assert drift == 0


def test_consecutive_marks_update_baseline():
    from daemon.clock import DriftDetector

    d = DriftDetector(threshold_seconds=30)
    with patch("daemon.clock.time.monotonic") as mock_mono:
        mock_mono.return_value = 100.0
        d.mark_sleep_start(60.0)
        mock_mono.return_value = 160.0
        d.detect_after_sleep()
        # 두 번째 사이클
        mock_mono.return_value = 200.0
        d.mark_sleep_start(60.0)
        mock_mono.return_value = 300.0  # 100s 흐름, 40s drift
        drift = d.detect_after_sleep()
        assert drift == 40

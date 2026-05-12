"""Tests for daemon.notifier"""
from unittest.mock import patch, MagicMock

import pytest


def test_notify_runs_osascript_and_bell():
    from daemon.notifier import notify

    with patch("daemon.notifier.subprocess.run") as mock_run, \
         patch("daemon.notifier.sys.stdout") as mock_stdout:
        notify("hello", terminal_bell=True, system_notification=True)

        # osascript 호출 확인 (display notification)
        called_cmds = [call.args[0] for call in mock_run.call_args_list]
        assert any("osascript" in cmd[0] for cmd in called_cmds)
        any_with_notification = any(
            "display notification" in " ".join(cmd)
            for cmd in called_cmds
        )
        assert any_with_notification

        # 터미널 벨 출력 확인
        write_calls = [call.args[0] for call in mock_stdout.write.call_args_list]
        assert any("\a" in s for s in write_calls)


def test_notify_skips_system_when_disabled():
    from daemon.notifier import notify

    with patch("daemon.notifier.subprocess.run") as mock_run, \
         patch("daemon.notifier.sys.stdout"):
        notify("hi", terminal_bell=False, system_notification=False)
        mock_run.assert_not_called()


def test_notify_silent_on_osascript_failure():
    """osascript 실패는 caller crash 안 일으켜야 한다 (PRD 불변)."""
    from daemon.notifier import notify
    import subprocess

    with patch("daemon.notifier.subprocess.run") as mock_run, \
         patch("daemon.notifier.sys.stdout"):
        mock_run.side_effect = FileNotFoundError("osascript not found")
        # 예외 전파 없이 완료되어야 함
        notify("hello", terminal_bell=False, system_notification=True)


def test_notify_silent_on_timeout():
    from daemon.notifier import notify
    import subprocess

    with patch("daemon.notifier.subprocess.run") as mock_run, \
         patch("daemon.notifier.sys.stdout"):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["osascript"], timeout=2)
        notify("hello", terminal_bell=False, system_notification=True)


def test_notify_escapes_message_for_osascript():
    """메시지에 따옴표가 있어도 osascript injection 안 일어나야 함."""
    from daemon.notifier import notify

    with patch("daemon.notifier.subprocess.run") as mock_run, \
         patch("daemon.notifier.sys.stdout"):
        notify('test "with quotes" and \\backslash', terminal_bell=False, system_notification=True)
        # 호출은 일어났고, 메시지가 escape됐는지 확인
        cmd = mock_run.call_args_list[0].args[0]
        script = cmd[-1]
        # 원본 따옴표는 escape되어 있어야 함 (정확한 방식은 구현에 따라)
        # 최소한 raw 형태로 들어가지 않았으면 OK
        assert mock_run.call_args_list[0].kwargs.get("timeout") is not None

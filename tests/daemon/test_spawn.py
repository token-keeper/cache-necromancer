"""Tests for daemon.spawn"""
from unittest.mock import patch, MagicMock


def test_spawn_skips_when_daemon_alive():
    from daemon.spawn import spawn_daemon_if_needed

    with patch("daemon.spawn.is_daemon_alive", return_value=True) as mock_alive, \
         patch("daemon.spawn.subprocess.Popen") as mock_popen:
        spawn_daemon_if_needed()
        mock_popen.assert_not_called()


def test_spawn_starts_when_daemon_dead():
    from daemon.spawn import spawn_daemon_if_needed

    with patch("daemon.spawn.is_daemon_alive", return_value=False), \
         patch("daemon.spawn.subprocess.Popen") as mock_popen:
        spawn_daemon_if_needed()
        mock_popen.assert_called_once()
        # detached / silent
        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True
        assert kwargs.get("close_fds") is True


def test_spawn_silent_on_oserror():
    """spawn 실패는 caller crash 안 일으켜야 한다."""
    from daemon.spawn import spawn_daemon_if_needed

    with patch("daemon.spawn.is_daemon_alive", return_value=False), \
         patch("daemon.spawn.subprocess.Popen", side_effect=OSError("fork failed")):
        # 예외 전파 없이 완료
        spawn_daemon_if_needed()


def test_spawn_silent_on_filenotfound():
    from daemon.spawn import spawn_daemon_if_needed

    with patch("daemon.spawn.is_daemon_alive", return_value=False), \
         patch("daemon.spawn.subprocess.Popen", side_effect=FileNotFoundError("python missing")):
        spawn_daemon_if_needed()

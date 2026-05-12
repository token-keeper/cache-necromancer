"""macOS 시스템 알림 + 터미널 벨.

실패는 silent (PRD 불변: 알림 실패가 daemon/hook crash를 일으키면 안 됨).
osascript는 2초 timeout으로 hang 방어.
"""
import subprocess
import sys


def _escape_for_applescript(text: str) -> str:
    """AppleScript string literal escape: 백슬래시와 따옴표를 escape."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(
    message: str,
    *,
    terminal_bell: bool = True,
    system_notification: bool = True,
    title: str = "cache-necromancer",
) -> None:
    """macOS 알림 + 터미널 벨. 실패는 silent.

    Args:
        message: 알림 본문.
        terminal_bell: 터미널 벨 (``\\a``) 출력 여부.
        system_notification: macOS osascript 알림 호출 여부.
        title: 알림 제목.
    """
    if terminal_bell:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except OSError:
            pass

    if system_notification:
        safe_msg = _escape_for_applescript(message)
        safe_title = _escape_for_applescript(title)
        script = f'display notification "{safe_msg}" with title "{safe_title}"'
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                timeout=2,
            )
        except (
            subprocess.TimeoutExpired,
            FileNotFoundError,
            OSError,
        ):
            pass  # silent

"""macOS osascript 알림 wrapper. 실패 silent (best-effort)."""
import subprocess


def notify(message: str, title: str = "cache-necromancer") -> None:
    """macOS 알림 발송. osascript 미설치 / 권한 거부 / timeout 등은 silent.

    호출자가 success 여부에 의존하지 않도록 best-effort 설계.
    """
    escaped_msg = message.replace('"', '\\"')
    escaped_title = title.replace('"', '\\"')
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{escaped_msg}" with title "{escaped_title}"',
            ],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

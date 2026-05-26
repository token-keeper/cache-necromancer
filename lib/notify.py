"""macOS osascript 알림 wrapper. 실패 silent (best-effort)."""
import subprocess


def _osa_escape(s: str) -> str:
    """osascript double-quoted string 이스케이프 — 백슬래시 먼저, 쌍따옴표 다음."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(
    message: str,
    title: str = "cache-necromancer",
    subtitle: str = "",
) -> None:
    """macOS 알림 발송. osascript 미설치 / 권한 거부 / timeout 등은 silent.

    호출자가 success 여부에 의존하지 않도록 best-effort 설계.
    subtitle 빈 문자열이면 with 절에서 생략.
    """
    parts = [f'display notification "{_osa_escape(message)}"']
    parts.append(f'with title "{_osa_escape(title)}"')
    if subtitle:
        parts.append(f'subtitle "{_osa_escape(subtitle)}"')
    try:
        subprocess.run(
            ["osascript", "-e", " ".join(parts)],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

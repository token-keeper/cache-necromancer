"""터미널 표시폭 계산 + round 박스 렌더 (순수 함수, 부수효과 0).

recap 박스 모드용. 이모지(2칸)·CJK(2칸)·variation selector(0칸) 보정으로
우변 테두리를 정렬한다. stdlib 만 사용.
"""
import unicodedata


def display_width(s: str) -> int:
    """문자열의 터미널 표시폭(컬럼 수) 합."""
    total = 0
    for ch in s:
        o = ord(ch)
        if o in (0x200D,) or 0xFE00 <= o <= 0xFE0F:  # ZWJ / variation selector
            continue
        if unicodedata.combining(ch):
            continue
        if (
            0x1F300 <= o <= 0x1FAFF
            or 0x2600 <= o <= 0x27BF
            or 0x1F000 <= o <= 0x1F2FF
            or o in (0x2B50, 0x2B55)
        ):
            total += 2
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


def render_box(lines: list[str], pad: int = 2) -> str:
    """lines 를 round 테두리 박스로 감싼 문자열(개행 포함)."""
    inner = max(display_width(l) for l in lines) + pad * 2
    out = ["╭" + "─" * inner + "╮"]
    for l in lines:
        fill = inner - display_width(l) - pad
        out.append("│" + " " * pad + l + " " * fill + "│")
    out.append("╰" + "─" * inner + "╯")
    return "\n".join(out)

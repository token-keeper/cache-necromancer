"""Unicode 박스 그리기 표 렌더러 — 한글 wide-char 보정.

`unicodedata.east_asian_width` 로 컬럼 셀 폭을 계산. 한글/한자/일본어 = 2 cell,
영문/ASCII = 1 cell. 자주 쓰는 이모지는 명시적 wide 매핑.

사용 예:
    box_section("데몬", ["살아있음 · PID 56949"])
    box_table("세션", ["sid", "next"], [["aec4b932", "7m 30s"]])
"""
import unicodedata

_EXTRA_WIDE_CHARS = {"✅", "🛑", "⚠", "⚡", "🔮", "◉", "●", "○", "■", "□", "★", "☆"}
_ZERO_WIDTH = {"️", "︎", "‍"}  # VS-16, VS-15, ZWJ


def display_width(s: str) -> int:
    """문자열의 시각적 컬럼 폭. 한글/한자/이모지 = 2, 나머지 = 1.

    Variation selector (FE0F 등) 와 결합 마크는 0-width.
    """
    w = 0
    for c in s:
        if c in _ZERO_WIDTH:
            continue
        if unicodedata.category(c) in ("Mn", "Me", "Cf"):
            continue
        if c in _EXTRA_WIDE_CHARS:
            w += 2
        elif unicodedata.east_asian_width(c) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def pad_right(s: str, width: int) -> str:
    diff = width - display_width(s)
    return s + " " * max(0, diff)


def _border_top(title: str, inner_width: int) -> str:
    title_segment = f"─ {title} " if title else "─"
    fill = inner_width - display_width(title_segment)
    return "┌" + title_segment + "─" * max(0, fill) + "┐"


def _border_bottom(inner_width: int) -> str:
    return "└" + "─" * inner_width + "┘"


def box_section(title: str, lines: list[str], min_width: int = 0) -> list[str]:
    """단순 박스 — 제목 + 본문 라인들. 가변 너비.

    inner_width = 본문 줄 중 가장 긴 것 + 좌우 padding 1. min_width 보장.
    """
    body_widths = [display_width(line) for line in lines] if lines else [0]
    inner = max(min_width, max(body_widths) + 2, display_width(f"─ {title} ") + 2)
    out = [_border_top(title, inner)]
    for line in lines:
        out.append("│ " + pad_right(line, inner - 2) + " │")
    out.append(_border_bottom(inner))
    return out


def box_table(title: str, headers: list[str], rows: list[list[str]],
              min_width: int = 0, row_separator: bool = False) -> list[str]:
    """박스 표 — 제목 + 헤더 행 + 본문 행들.

    각 컬럼 너비는 헤더와 본문의 최대값. 구분자 ' │ ' 사용.
    ``row_separator=True`` 시 본문 행 사이에 ├─┼─┤ 분리선 삽입.
    """
    n = len(headers)
    col_widths = [display_width(h) for h in headers]
    for row in rows:
        for i in range(min(n, len(row))):
            col_widths[i] = max(col_widths[i], display_width(row[i]))

    sep = " │ "
    # 셀 내용 + 좌우 1-space padding 포함한 너비 = col_w + 2
    # 표 전체 inner 너비: " col1 │ col2 │ col3 " 형태
    inner = sum(col_widths) + (n - 1) * len(sep) + 2  # +2 = 양끝 공백
    inner = max(inner, min_width, display_width(f"─ {title} ") + 2)

    def _format_row(cells: list[str]) -> str:
        parts = [pad_right(cells[i] if i < len(cells) else "", col_widths[i])
                 for i in range(n)]
        body = " " + sep.join(parts) + " "
        return "│" + pad_right(body, inner) + "│"

    def _mid_separator() -> str:
        # ├─┼─┼─┤ 형태
        cells = []
        for i, w in enumerate(col_widths):
            # 셀 너비 + 양쪽 1-space padding = w + 2
            if i == 0:
                cells.append("─" * (w + 2))
            else:
                cells.append("┼" + "─" * (w + 2))
        # 마지막에 trailing 채우기 (inner 까지)
        joined = "".join(cells)
        # inner 와 길이 맞추기
        return "├" + pad_right(joined, inner).replace(" ", "─") + "┤"

    out = [_border_top(title, inner), _format_row(headers), _mid_separator()]
    for i, row in enumerate(rows):
        if i > 0 and row_separator:
            out.append(_mid_separator())
        out.append(_format_row(row))
    out.append(_border_bottom(inner))
    return out


def render(*parts: list[str]) -> str:
    """여러 박스를 빈 줄 한 줄로 이어붙임."""
    chunks = []
    for p in parts:
        chunks.append("\n".join(p))
    return "\n\n".join(chunks)


def wrap_outer(title: str, body_lines: list[str], min_width: int = 0) -> list[str]:
    """주어진 라인들을 outer 박스로 감쌈 (각 라인 앞뒤 │ 추가)."""
    if not body_lines:
        body_lines = [""]
    body_max = max(display_width(line) for line in body_lines)
    inner = max(min_width, body_max + 2, display_width(f"─ {title} ") + 2)
    out = [_border_top(title, inner)]
    for line in body_lines:
        out.append("│ " + pad_right(line, inner - 2) + " │")
    out.append(_border_bottom(inner))
    return out

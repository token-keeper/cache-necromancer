"""Tests for lib/box_renderer.py — 박스 그리기 + 한글 wide-char 처리."""
from lib.box_renderer import (
    box_section,
    box_table,
    display_width,
    pad_right,
    render,
    wrap_outer,
)


def test_display_width_ascii():
    assert display_width("hello") == 5
    assert display_width("") == 0


def test_display_width_korean():
    assert display_width("세션") == 4  # 한글 = 2 cell × 2
    assert display_width("sid") == 3


def test_display_width_emoji_with_variation_selector():
    """⚠️ = U+26A0 + U+FE0F (variation selector). VS-16 은 0-width 처리."""
    assert display_width("⚠️") == 2
    assert display_width("✅") == 2
    assert display_width("🛑") == 2


def test_display_width_mixed():
    assert display_width("✅ 살아있음") == 2 + 1 + 8


def test_pad_right_handles_wide_chars():
    """한글 폭을 고려한 padding."""
    padded = pad_right("세션", 10)
    assert display_width(padded) == 10
    assert padded.startswith("세션")


def test_box_section_simple():
    box = box_section("title", ["line1", "line2"])
    # ┌─ title ─┐ / │ ... │ × 2 / └─...─┘ = 4 lines
    assert len(box) == 4
    assert box[0].startswith("┌─ title ")
    assert box[-1].startswith("└")
    assert "line1" in box[1]
    assert "line2" in box[2]


def test_box_section_min_width():
    """min_width 보다 작은 내용도 min_width 폭으로 확장."""
    box = box_section("t", ["a"], min_width=40)
    # 각 박스 line 폭 = inner + 2 (좌우 │) ≥ min_width + 2 = 42
    for line in box:
        assert display_width(line) >= 42


def test_box_section_empty_title():
    """title 없으면 단순한 상단 border."""
    box = box_section("", ["content"])
    assert box[0].startswith("┌")
    assert "content" in box[1]


def test_box_table_columns_align():
    """box_table 의 각 행이 동일한 폭."""
    box = box_table(
        "test",
        ["A", "B", "C"],
        [["1", "22", "333"], ["x", "yy", "zzz"]],
    )
    widths = [display_width(line) for line in box]
    # 모든 라인이 동일 폭
    assert len(set(widths)) == 1


def test_box_table_row_separator():
    """row_separator=True 시 본문 행 사이에 ├─┼─┤ 구분선."""
    box = box_table(
        "t",
        ["A", "B"],
        [["1", "2"], ["3", "4"], ["5", "6"]],
        row_separator=True,
    )
    # 헤더 mid_sep + 본문 행 사이 mid_sep × 2 = 총 3 개의 mid_sep
    mid_sep_lines = [line for line in box if line.startswith("├")]
    assert len(mid_sep_lines) == 3  # 헤더 아래 + 행 사이 2개


def test_box_table_without_row_separator():
    """기본은 row_separator 없음 — 헤더 아래 mid_sep 만 1개."""
    box = box_table(
        "t",
        ["A", "B"],
        [["1", "2"], ["3", "4"]],
    )
    mid_sep_lines = [line for line in box if line.startswith("├")]
    assert len(mid_sep_lines) == 1


def test_box_table_korean_columns():
    """한글 컬럼 헤더 / 셀이 폭 정확히 정렬됨."""
    box = box_table(
        "한글",
        ["sid", "상태"],
        [["abc", "정상"]],
    )
    widths = [display_width(line) for line in box]
    assert len(set(widths)) == 1  # 모든 라인 동일 폭


def test_wrap_outer_basic():
    """wrap_outer 가 body lines 를 outer 박스로 감쌈."""
    body = ["line1", "line2", "line3"]
    outer = wrap_outer("외곽", body)
    assert outer[0].startswith("┌─ 외곽 ")
    assert outer[-1].startswith("└")
    # body 각 줄이 │ ... │ 형태로 감싸짐
    for body_line in body:
        assert any(body_line in line and line.startswith("│") for line in outer)


def test_wrap_outer_min_width():
    """min_width 가 outer 박스 폭을 강제."""
    outer = wrap_outer("t", ["short"], min_width=50)
    for line in outer:
        # outer 박스 폭 = inner + 2 ≥ 52
        assert display_width(line) >= 52


def test_render_joins_with_blank_line():
    """render 가 여러 박스를 빈 줄로 분리해 join."""
    box1 = box_section("a", ["x"])
    box2 = box_section("b", ["y"])
    result = render(box1, box2)
    assert "\n\n" in result  # 빈 줄로 분리
    assert "a" in result
    assert "b" in result

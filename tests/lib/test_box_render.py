import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.box_render import display_width, render_box


def test_display_width_ascii():
    assert display_width("Cache dies at 17:44") == 19


def test_display_width_skull_with_variation_selector():
    # ☠️ = U+2620 + U+FE0F → 표시폭 2 (FE0F 는 0)
    assert display_width("☠️") == 2


def test_display_width_tombstone_and_cjk():
    assert display_width("🪦") == 2          # U+1FAA6
    assert display_width("캐시") == 4         # CJK 2글자 × 2


def test_render_box_all_lines_same_display_width():
    lines = ["🪦  Cache dies at 17:44", "🔥  3 wakes · until 20:14"]
    out = render_box(lines).split("\n")
    widths = {display_width(l) for l in out}
    assert len(widths) == 1, f"행마다 폭 불일치: {widths}"


def test_render_box_border_chars():
    out = render_box(["x"]).split("\n")
    assert out[0][0] == "╭" and out[0][-1] == "╮"
    assert out[1][0] == "│" and out[1][-1] == "│"
    assert out[-1][0] == "╰" and out[-1][-1] == "╯"

"""Tests for lib/i18n.py (recap 메시지 4 언어 + fallback)."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    build_recap_message,
    normalize_language,
)


def test_default_language_is_en():
    assert DEFAULT_LANGUAGE == "en"


def test_supported_languages_are_four():
    assert set(SUPPORTED_LANGUAGES) == {"ko", "en", "ja", "zh"}


@pytest.mark.parametrize("lang,hh,mm,expected", [
    ("ko", 10, 50, "🪦 캐시는 10시 50분에 죽어요."),
    ("en", 10, 50, "🪦 Cache dies at 10:50."),
    ("ja", 10, 50, "🪦 キャッシュは10時50分に死にます。"),
    ("zh", 10, 50, "🪦 缓存将在10点50分死亡。"),
    ("en", 0, 5, "🪦 Cache dies at 00:05."),
    ("ko", 0, 5, "🪦 캐시는 0시 5분에 죽어요."),
    ("en", 23, 59, "🪦 Cache dies at 23:59."),
    ("ja", 0, 0, "🪦 キャッシュは0時0分に死にます。"),
    ("zh", 23, 59, "🪦 缓存将在23点59分死亡。"),
])
def test_build_recap_message(lang, hh, mm, expected):
    assert build_recap_message(lang, hh, mm) == expected


@pytest.mark.parametrize("lang", ["ko", "en", "ja", "zh"])
def test_normalize_language_valid(lang):
    assert normalize_language(lang) == lang


@pytest.mark.parametrize("invalid", ["xx", "kor", "english", None, 123, "", "KO"])
def test_normalize_language_invalid_falls_back_to_en(invalid, capsys):
    result = normalize_language(invalid)
    assert result == "en"
    err = capsys.readouterr().err.lower()
    assert "fallback" in err
    assert "unknown language" in err

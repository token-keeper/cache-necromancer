"""Tests for lib/i18n.py (라벨 4 언어 + fallback)."""
import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    SET_LABELS,
    STATUS_LABELS,
    SUPPORTED_LANGUAGES,
    normalize_language,
    set_label,
    status_label,
)


def test_default_language_is_en():
    assert DEFAULT_LANGUAGE == "en"


def test_supported_languages_are_four():
    assert set(SUPPORTED_LANGUAGES) == {"ko", "en", "ja", "zh"}


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


# ---------- STATUS_LABELS / status_label ----------

class TestStatusLabels:
    def test_all_four_languages_present(self):
        assert set(STATUS_LABELS.keys()) == {"ko", "en", "ja", "zh"}

    def test_all_languages_have_same_keys(self):
        en_keys = set(STATUS_LABELS["en"].keys())
        for lang in ("ko", "ja", "zh"):
            assert set(STATUS_LABELS[lang].keys()) == en_keys, (
                f"{lang} 의 키 셋이 en 과 불일치"
            )

    @pytest.mark.parametrize("lang,key,expected", [
        ("ko", "current_session", "세션 (현재)"),
        ("en", "current_session", "Session (current)"),
        ("ja", "current_session", "セッション (現在)"),
        ("zh", "current_session", "会话 (当前)"),
        ("ko", "cwd", "폴더"),
        ("en", "cwd", "cwd"),
        ("ja", "cwd", "ディレクトリ"),
        ("zh", "cwd", "目录"),
    ])
    def test_status_label_lookup(self, lang, key, expected):
        assert status_label(lang, key) == expected

    def test_status_label_unknown_key_returns_key(self):
        # 알 수 없는 키는 en fallback 도 없어 → key 그대로
        assert status_label("en", "totally-unknown-key") == "totally-unknown-key"

    def test_status_labels_placeholder_consistency(self):
        placeholder_re = re.compile(r"\{(\w+)\}")
        for key, en_val in STATUS_LABELS["en"].items():
            expect = set(placeholder_re.findall(en_val))
            for lang in ("ko", "ja", "zh"):
                got = set(placeholder_re.findall(STATUS_LABELS[lang][key]))
                assert got == expect, f"STATUS_LABELS[{lang!r}][{key!r}]"


# 옛 용어 — ko 는 "깨우기·살림"으로 통일 (v0.12.0)
_BANNED_KO = ("소생", "목숨", "예산", "arm", "fire", "발동", "repeat count")


class TestKoTerms:
    def test_ko_labels_use_unified_terms(self):
        for table in (STATUS_LABELS["ko"], SET_LABELS["ko"]):
            for key, val in table.items():
                for word in _BANNED_KO:
                    assert word not in val, f"ko {key!r} 에 옛 용어 {word!r}"


class TestRemovedApi:
    def test_arm_label_removed(self):
        import lib.i18n as i18n_mod
        assert not hasattr(i18n_mod, "arm_label_i18n")
        assert not hasattr(i18n_mod, "mode_label_i18n")


class TestSetLabels:
    def test_known_keys_all_langs(self):
        keys = ("status_off", "status_set", "status_auto", "status_auto_disabled",
                "turned_off", "charged", "capped_note", "session_only", "usage",
                "save_failed", "no_session", "until_time", "until_expired",
                "back_to_auto", "already_alive", "no_window", "no_live_cache")
        for lang in ("ko", "en", "ja", "zh"):
            assert set(SET_LABELS[lang].keys()) == set(keys)
            for k in keys:
                assert set_label(lang, k)

    def test_unknown_key_falls_back(self):
        assert set_label("ko", "no-such-key") == "no-such-key"

    def test_set_labels_placeholder_consistency(self):
        """각 키의 {placeholder} 집합이 4 언어 간에 동일해야 한다."""
        placeholder_re = re.compile(r"\{(\w+)\}")
        en_dict = SET_LABELS["en"]
        for key in en_dict:
            en_placeholders = set(placeholder_re.findall(en_dict[key]))
            for lang in ("ko", "ja", "zh"):
                lang_val = SET_LABELS[lang].get(key, "")
                lang_placeholders = set(placeholder_re.findall(lang_val))
                assert lang_placeholders == en_placeholders, (
                    f"SET_LABELS[{lang!r}][{key!r}] placeholder 불일치: "
                    f"en={en_placeholders}, {lang}={lang_placeholders}"
                )

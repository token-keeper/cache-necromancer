"""Tests for lib/i18n.py (recap 메시지 4 언어 + fallback)."""
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
    build_recap_message,
    normalize_language,
    set_label,
    status_label,
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

    def test_mode_key_absent(self):
        """v0.5.0: mode 키는 STATUS_LABELS 에서 제거됨."""
        for lang in ("ko", "en", "ja", "zh"):
            assert "mode" not in STATUS_LABELS[lang]

    def test_notify_warn_key_absent(self):
        """v0.5.0: notify_warn 키는 STATUS_LABELS 에서 제거됨."""
        for lang in ("ko", "en", "ja", "zh"):
            assert "notify_warn" not in STATUS_LABELS[lang]


class TestSetRecapLine:
    def test_ko(self):
        from lib.i18n import build_set_recap_line
        s = build_set_recap_line("ko", 2, 21, 40)
        assert "2" in s and "21시 40분" in s and s.startswith("🔥")

    def test_all_languages_nonempty(self):
        from lib.i18n import build_set_recap_line
        for lang in ("ko", "en", "ja", "zh"):
            assert build_set_recap_line(lang, 1, 9, 5)


class TestArmLabel:
    def test_manual_and_always_all_langs(self):
        from lib.i18n import arm_label_i18n
        for lang in ("ko", "en", "ja", "zh"):
            assert "manual" in arm_label_i18n(lang, "manual", True, 60)
            assert "always" in arm_label_i18n(lang, "always", False, 60)


class TestSetLabels:
    def test_known_keys_all_langs(self):
        keys = ("charged", "capped_note", "session_only", "first_turn_note",
                "cancelled", "status_armed", "status_none", "always_noop",
                "usage")
        for lang in ("ko", "en", "ja", "zh"):
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


class TestNewStatusLabels:
    def test_arm_set_budget_legacy_warn_all_langs(self):
        for lang in ("ko", "en", "ja", "zh"):
            assert status_label(lang, "arm")
            assert status_label(lang, "set_budget")
            assert "{keys}" in status_label(lang, "legacy_warn")


class TestModeLabelI18nRemoved:
    """v0.5.0: mode_label_i18n 은 lib/i18n.py 에서 삭제됨."""

    def test_mode_label_i18n_not_exported(self):
        import lib.i18n as i18n_mod
        assert not hasattr(i18n_mod, "mode_label_i18n"), (
            "mode_label_i18n 이 아직 i18n 모듈에 남아 있음 — 삭제 필요"
        )

"""Tests for lib/i18n.py (recap 메시지 4 언어 + fallback)."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    STATUS_LABELS,
    SUPPORTED_LANGUAGES,
    build_recap_message,
    mode_label_i18n,
    normalize_language,
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


# ---------- mode_label_i18n ----------

class TestModeLabelI18n:
    @pytest.mark.parametrize("lang,mode,fragment", [
        ("ko", "notify", "알림만"),
        ("en", "notify", "notify only"),
        ("ja", "notify", "通知のみ"),
        ("zh", "notify", "仅通知"),
        ("ko", "auto", "자동 wake"),
        ("en", "auto", "auto wake"),
        ("ja", "auto", "自動 wake"),
        ("zh", "auto", "自动 wake"),
    ])
    def test_basic_modes(self, lang, mode, fragment):
        out = mode_label_i18n(lang, mode, 60)
        assert fragment in out

    @pytest.mark.parametrize("lang", ["ko", "en", "ja", "zh"])
    def test_hybrid_includes_wait_seconds(self, lang):
        out = mode_label_i18n(lang, "hybrid", 45)
        assert "45" in out

    def test_unknown_mode_renders_question(self):
        out = mode_label_i18n("en", "weird", 60)
        assert "weird" in out
        assert "❓" in out


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
        from lib.i18n import set_label
        keys = ("charged", "capped_note", "session_only", "first_turn_note",
                "cancelled", "status_armed", "status_none", "always_noop",
                "usage")
        for lang in ("ko", "en", "ja", "zh"):
            for k in keys:
                assert set_label(lang, k)

    def test_unknown_key_falls_back(self):
        from lib.i18n import set_label
        assert set_label("ko", "no-such-key") == "no-such-key"


class TestNewStatusLabels:
    def test_arm_set_budget_legacy_warn_all_langs(self):
        from lib.i18n import status_label
        for lang in ("ko", "en", "ja", "zh"):
            assert status_label(lang, "arm")
            assert status_label(lang, "set_budget")
            assert "{keys}" in status_label(lang, "legacy_warn")

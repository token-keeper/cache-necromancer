"""recap 메시지 다국어 (ko/en/ja/zh).

PING 등 다른 메시지는 별도 PR 에서 i18n 화.
"""
import sys
from typing import Literal

Language = Literal["ko", "en", "ja", "zh"]
DEFAULT_LANGUAGE: Language = "en"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("ko", "en", "ja", "zh")


def _format_time(lang: Language, hh: int, mm: int) -> str:
    if lang == "ko":
        return f"{hh}시 {mm}분"
    if lang == "en":
        return f"{hh:02d}:{mm:02d}"
    if lang == "ja":
        return f"{hh}時{mm}分"
    if lang == "zh":
        return f"{hh}点{mm}分"
    return f"{hh:02d}:{mm:02d}"


def build_recap_message(lang: Language, hh: int, mm: int) -> str:
    time_str = _format_time(lang, hh, mm)
    if lang == "ko":
        return f"🪦 캐시는 {time_str}에 죽어요."
    if lang == "en":
        return f"🪦 Cache dies at {time_str}."
    if lang == "ja":
        return f"🪦 キャッシュは{time_str}に死にます。"
    if lang == "zh":
        return f"🪦 缓存将在{time_str}死亡。"
    return f"🪦 Cache dies at {time_str}."


def normalize_language(value: object) -> Language:
    if isinstance(value, str) and value in SUPPORTED_LANGUAGES:
        return value  # type: ignore[return-value]
    print(
        f"[cn:warn] unknown language={value!r}, fallback to {DEFAULT_LANGUAGE!r}",
        file=sys.stderr,
    )
    return DEFAULT_LANGUAGE

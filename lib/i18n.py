"""다국어 메시지 / 라벨 (ko/en/ja/zh).

용도:
  - recap 메시지 (Stop hook sync) — `build_recap_message`
  - /cn:status 박스 라벨 + mode 한 줄 설명 — `STATUS_LABELS`, `mode_label_i18n`
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


# /cn:status 박스 라벨 + 텍스트
STATUS_LABELS: dict[Language, dict[str, str]] = {
    "ko": {
        "title": "🔮 cache-necromancer",
        "current_session": "세션 (현재)",
        "other_sessions": "다른 세션",
        "status": "상태",
        "sid": "sid",
        "repeat_count": "repeat count",
        "next_fire": "다음 발동 예상",
        "prompt": "prompt",
        "cwd": "폴더",
        "mode": "mode",
        "settings": "설정",
        "plugin": "plugin",
        "none": "없음",
        "no_other": "없음",
        "more_n": "외 {n}개 (오래된 stale marker)",
        "notify_warn": "⚠️  mode=notify — cache 갱신 효과 없음 (알림 only)",
        "config_parse_warn": "⚠️  config.toml 파싱 실패: {err} — 기본값 사용 중",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (무시됨)",
    },
    "en": {
        "title": "🔮 cache-necromancer",
        "current_session": "Session (current)",
        "other_sessions": "Other sessions",
        "status": "Status",
        "sid": "sid",
        "repeat_count": "repeat count",
        "next_fire": "next fire",
        "prompt": "prompt",
        "cwd": "cwd",
        "mode": "mode",
        "settings": "settings",
        "plugin": "plugin",
        "none": "none",
        "no_other": "none",
        "more_n": "and {n} more (stale markers)",
        "notify_warn": "⚠️  mode=notify — no cache refresh effect (notify only)",
        "config_parse_warn": "⚠️  config.toml parse failed: {err} — using defaults",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (ignored)",
    },
    "ja": {
        "title": "🔮 cache-necromancer",
        "current_session": "セッション (現在)",
        "other_sessions": "他のセッション",
        "status": "状態",
        "sid": "sid",
        "repeat_count": "repeat count",
        "next_fire": "次回発動予定",
        "prompt": "prompt",
        "cwd": "ディレクトリ",
        "mode": "mode",
        "settings": "設定",
        "plugin": "plugin",
        "none": "なし",
        "no_other": "なし",
        "more_n": "他 {n} 件 (古い stale marker)",
        "notify_warn": "⚠️  mode=notify — cache 更新効果なし (通知のみ)",
        "config_parse_warn": "⚠️  config.toml パース失敗: {err} — デフォルト使用",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (無視)",
    },
    "zh": {
        "title": "🔮 cache-necromancer",
        "current_session": "会话 (当前)",
        "other_sessions": "其他会话",
        "status": "状态",
        "sid": "sid",
        "repeat_count": "repeat count",
        "next_fire": "下次触发",
        "prompt": "prompt",
        "cwd": "目录",
        "mode": "mode",
        "settings": "设置",
        "plugin": "plugin",
        "none": "无",
        "no_other": "无",
        "more_n": "另有 {n} 个 (过期 stale marker)",
        "notify_warn": "⚠️  mode=notify — 缓存无刷新效果 (仅通知)",
        "config_parse_warn": "⚠️  config.toml 解析失败: {err} — 使用默认值",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (已忽略)",
    },
}


def status_label(lang: Language, key: str) -> str:
    """STATUS_LABELS lookup. 없으면 en fallback, 그래도 없으면 key 그대로."""
    return STATUS_LABELS.get(lang, STATUS_LABELS["en"]).get(
        key, STATUS_LABELS["en"].get(key, key)
    )


def mode_label_i18n(lang: Language, mode: str, hybrid_wait_seconds: int) -> str:
    """현재 mode 한 줄 — emoji + 동작 요약 (다국어).

    config 객체 의존 X — wait seconds 만 받음 (test 단순화).
    """
    if mode == "notify":
        return {
            "ko": "🔔 notify — 알림만 (wake 안 함, cache 갱신 효과 0)",
            "en": "🔔 notify — notify only (no wake, no cache refresh)",
            "ja": "🔔 notify — 通知のみ (wake なし, cache 更新なし)",
            "zh": "🔔 notify — 仅通知 (无 wake, 无缓存刷新)",
        }[lang]
    if mode == "auto":
        return {
            "ko": "⚡ auto — sleep 후 자동 wake (chat 세션 self-wake)",
            "en": "⚡ auto — sleep then auto wake (chat session self-wake)",
            "ja": "⚡ auto — sleep 後に自動 wake (chat セッション self-wake)",
            "zh": "⚡ auto — sleep 后自动 wake (chat 会话 self-wake)",
        }[lang]
    if mode == "hybrid":
        return {
            "ko": f"💀 hybrid — 알림 → {hybrid_wait_seconds}s 안에 입력 없으면 wake (취소 가능)",
            "en": f"💀 hybrid — notify → wake if no input within {hybrid_wait_seconds}s (cancelable)",
            "ja": f"💀 hybrid — 通知 → {hybrid_wait_seconds}s 内に入力なければ wake (キャンセル可)",
            "zh": f"💀 hybrid — 通知 → {hybrid_wait_seconds}s 内无输入则 wake (可取消)",
        }[lang]
    return f"❓ {mode}"

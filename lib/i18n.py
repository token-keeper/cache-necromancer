"""다국어 메시지 / 라벨 (ko/en/ja/zh).

용도:
  - recap 메시지 (Stop hook sync) — `build_recap_message`, `build_set_recap_line`
  - /cn:status 박스 라벨 + arm 한 줄 설명 — `STATUS_LABELS`, `arm_label_i18n`
  - /cn:set 응답 / 상태 문구 — `SET_LABELS`, `set_label`
  - arm 정책 한 줄 설명 — `arm_label_i18n`
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


def build_set_recap_line(lang: Language, remaining: int, hh: int, mm: int) -> str:
    """recap 2줄째 — set 예산 잔량 + 최대 생존 시한 (spec §8)."""
    time_str = _format_time(lang, hh, mm)
    if lang == "ko":
        return f"🔥 wake {remaining}회 남음 — 최대 {time_str}까지 생존"
    if lang == "en":
        return f"🔥 {remaining} wake(s) left — alive until {time_str} at most"
    if lang == "ja":
        return f"🔥 wake 残り{remaining}回 — 最大{time_str}まで生存"
    if lang == "zh":
        return f"🔥 剩余 {remaining} 次 wake — 最长存活至{time_str}"
    return f"🔥 {remaining} wake(s) left — alive until {time_str} at most"


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
        "settings": "설정",
        "plugin": "plugin",
        "none": "없음",
        "no_other": "없음",
        "more_n": "외 {n}개 (오래된 stale marker)",
        "config_parse_warn": "⚠️  config.toml 파싱 실패: {err} — 기본값 사용 중",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (무시됨)",
        "arm": "arm",
        "set_budget": "set",
        "legacy_warn": "⚠️  v0.4.x config 키 감지 ({keys}) — 자동 매핑됨. /cn:config 재설정 권장",
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
        "settings": "settings",
        "plugin": "plugin",
        "none": "none",
        "no_other": "none",
        "more_n": "and {n} more (stale markers)",
        "config_parse_warn": "⚠️  config.toml parse failed: {err} — using defaults",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (ignored)",
        "arm": "arm",
        "set_budget": "set",
        "legacy_warn": "⚠️  legacy v0.4.x config keys ({keys}) — auto-mapped. Re-run /cn:config",
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
        "settings": "設定",
        "plugin": "plugin",
        "none": "なし",
        "no_other": "なし",
        "more_n": "他 {n} 件 (古い stale marker)",
        "config_parse_warn": "⚠️  config.toml パース失敗: {err} — デフォルト使用",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (無視)",
        "arm": "arm",
        "set_budget": "set",
        "legacy_warn": "⚠️  v0.4.x config キー検出 ({keys}) — 自動マッピング。/cn:config 推奨",
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
        "settings": "设置",
        "plugin": "plugin",
        "none": "无",
        "no_other": "无",
        "more_n": "另有 {n} 个 (过期 stale marker)",
        "config_parse_warn": "⚠️  config.toml 解析失败: {err} — 使用默认值",
        "deprecated_warn": "⚠️  deprecated v0.2.x config: {keys} (已忽略)",
        "arm": "arm",
        "set_budget": "set",
        "legacy_warn": "⚠️  检测到 v0.4.x config 键 ({keys}) — 已自动映射。建议 /cn:config",
    },
}


def status_label(lang: Language, key: str) -> str:
    """STATUS_LABELS lookup. 없으면 en fallback, 그래도 없으면 key 그대로."""
    return STATUS_LABELS.get(lang, STATUS_LABELS["en"]).get(
        key, STATUS_LABELS["en"].get(key, key)
    )


def arm_label_i18n(lang: Language, arm: str, notify_enabled: bool, grace_seconds: int) -> str:
    """현재 arm 정책 한 줄 — /cn:status 용 (v0.5.0)."""
    n = "🔔" if notify_enabled else "🔕"
    if arm == "always":
        if notify_enabled:
            return {
                "ko": f"⚡ always — 매 turn 자동 arm · {n} 알림 후 {grace_seconds}s 내 입력 없으면 wake",
                "en": f"⚡ always — auto-arm every turn · {n} notify, wake after {grace_seconds}s",
                "ja": f"⚡ always — 毎 turn 自動 arm · {n} 通知後 {grace_seconds}s で wake",
                "zh": f"⚡ always — 每 turn 自动 arm · {n} 通知后 {grace_seconds}s wake",
            }[lang]
        return {
            "ko": f"⚡ always — 매 turn 자동 arm · {n} 알림 없이 즉시 wake",
            "en": f"⚡ always — auto-arm every turn · {n} immediate wake",
            "ja": f"⚡ always — 毎 turn 自動 arm · {n} 即時 wake",
            "zh": f"⚡ always — 每 turn 自动 arm · {n} 立即 wake",
        }[lang]
    return {
        "ko": f"🪄 manual — /cn:set 충전분만 소생 · {n} 만료 임박 알림",
        "en": f"🪄 manual — revive only /cn:set budget · {n} expiry notify",
        "ja": f"🪄 manual — /cn:set 充電分のみ蘇生 · {n} 期限通知",
        "zh": f"🪄 manual — 仅复活 /cn:set 充值 · {n} 到期通知",
    }[lang]


# /cn:set 응답 문구 ({n}=충전/잔여, {req}=요청, {max}=상한, {time}=생존 시한, {total}=충전량)
SET_LABELS: dict[Language, dict[str, str]] = {
    "ko": {
        "charged": "🔥 wake {n}회 충전 — 캐시는 최대 {time}까지 생존",
        "capped_note": "(요청 {req}회 → 상한 max_refresh_count={max}회로 제한)",
        "session_only": "이 세션만 충전됩니다 — 다른 세션은 각자 /cn:set 필요.",
        "first_turn_note": "⚠️  이 세션은 아직 fire 가 없어 보호는 다음 turn 종료부터 시작됩니다.",
        "cancelled": "set 예산을 취소했습니다 (0회).",
        "status_armed": "🔥 wake {n}회 남음 (충전 {total}회) — 최대 {time}까지 생존",
        "status_none": "set 없음 — /cn:set N 으로 충전하세요.",
        "always_noop": "arm=always — 상시 자동 갱신 중이라 set 이 불필요합니다. set 운용으로 바꾸려면 /cn:config 에서 arm=manual.",
        "usage": "사용법: /cn:set N (N=wake 횟수, 0=취소, 무인자=상태)",
    },
    "en": {
        "charged": "🔥 charged {n} wake(s) — cache alive until {time} at most",
        "capped_note": "(requested {req} → capped at max_refresh_count={max})",
        "session_only": "This session only — run /cn:set in other sessions separately.",
        "first_turn_note": "⚠️  No fire yet in this session — protection starts after the next turn.",
        "cancelled": "Set budget cancelled (0).",
        "status_armed": "🔥 {n} wake(s) left (charged {total}) — alive until {time} at most",
        "status_none": "No set budget — charge with /cn:set N.",
        "always_noop": "arm=always — auto-refresh every turn, set not needed. Switch via /cn:config (arm=manual).",
        "usage": "Usage: /cn:set N (N=wakes, 0=cancel, no arg=status)",
    },
    "ja": {
        "charged": "🔥 wake {n}回充電 — キャッシュは最大{time}まで生存",
        "capped_note": "(要求 {req}回 → 上限 max_refresh_count={max}回)",
        "session_only": "このセッションのみ — 他セッションは個別に /cn:set。",
        "first_turn_note": "⚠️  このセッションはまだ fire なし — 保護は次の turn 終了から。",
        "cancelled": "set 予算を取消しました (0回)。",
        "status_armed": "🔥 wake 残り{n}回 (充電{total}回) — 最大{time}まで生存",
        "status_none": "set なし — /cn:set N で充電。",
        "always_noop": "arm=always — 常時自動更新中のため set 不要。変更は /cn:config (arm=manual)。",
        "usage": "使い方: /cn:set N (N=wake 回数, 0=取消, 無引数=状態)",
    },
    "zh": {
        "charged": "🔥 已充值 {n} 次 wake — 缓存最长存活至{time}",
        "capped_note": "(请求 {req} 次 → 上限 max_refresh_count={max})",
        "session_only": "仅本会话 — 其他会话需各自 /cn:set。",
        "first_turn_note": "⚠️  本会话尚无 fire — 保护从下个 turn 结束开始。",
        "cancelled": "已取消 set 预算 (0)。",
        "status_armed": "🔥 剩余 {n} 次 wake (充值 {total}) — 最长存活至{time}",
        "status_none": "无 set 预算 — 用 /cn:set N 充值。",
        "always_noop": "arm=always — 每 turn 自动刷新, 无需 set。修改: /cn:config (arm=manual)。",
        "usage": "用法: /cn:set N (N=wake 次数, 0=取消, 无参数=状态)",
    },
}


def set_label(lang: Language, key: str) -> str:
    """SET_LABELS lookup. 없으면 en fallback, 그래도 없으면 key 그대로."""
    return SET_LABELS.get(lang, SET_LABELS["en"]).get(
        key, SET_LABELS["en"].get(key, key)
    )

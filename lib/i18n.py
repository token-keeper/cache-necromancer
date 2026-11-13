"""다국어 메시지 / 라벨 (ko/en/ja/zh).

용도:
  - /cn:status 박스 라벨·값 — `STATUS_LABELS`, `status_label`
  - /cn:set 응답 / 상태 문구 — `SET_LABELS`, `set_label`

ko 용어는 "깨우기·살림"으로 통일한다.
"""
import sys
from typing import Literal

Language = Literal["ko", "en", "ja", "zh"]
DEFAULT_LANGUAGE: Language = "en"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("ko", "en", "ja", "zh")


def normalize_language(value: object) -> Language:
    if isinstance(value, str) and value in SUPPORTED_LANGUAGES:
        return value  # type: ignore[return-value]
    print(
        f"[cn:warn] unknown language={value!r}, fallback to {DEFAULT_LANGUAGE!r}",
        file=sys.stderr,
    )
    return DEFAULT_LANGUAGE


# /cn:status 박스 라벨 + 값 ({n}=횟수, {i}=interval, {t}=ttl)
STATUS_LABELS: dict[Language, dict[str, str]] = {
    "ko": {
        "title": "🔮 cache-necromancer",
        "current_session": "세션 (현재)",
        "other_sessions": "다른 세션",
        "status": "상태",
        "sid": "sid",
        "wake": "깨우기",
        "woken": "살림",
        "next_wake": "다음 깨우기",
        "alive_until": "캐시 최대",
        "expired": "이미 만료 — 다음 자리비움부터",
        "prompt": "prompt",
        "cwd": "폴더",
        "auto_wakes": "자동 깨우기",
        "settings": "설정",
        "plugin": "plugin",
        "none": "없음",
        "no_other": "없음",
        "more_n": "외 {n}개 (오래된 stale marker)",
        "state_off": "꺼짐 (이 세션)",
        "state_set": "/cn:set 덮어쓰기 · {n}회 남음",
        "state_auto": "자동 · {n}회 남음",
        "state_no_window": "깨울 수 없음 (interval ≥ ttl)",
        "woken_value": "{n}번 (이번 자리비움)",
        "auto_per_away": "자리비움마다 {n}회",
        "auto_disabled": "꺼짐",
        "settings_value": "interval {i}분 · ttl {t}분",
        "obsolete_warn": "⚠️  무시되는 옛 설정 {n}개 — /cn:config 저장 시 정리",
    },
    "en": {
        "title": "🔮 cache-necromancer",
        "current_session": "Session (current)",
        "other_sessions": "Other sessions",
        "status": "Status",
        "sid": "sid",
        "wake": "wake",
        "woken": "revived",
        "next_wake": "next wake",
        "alive_until": "cache until",
        "expired": "already expired — from the next away",
        "prompt": "prompt",
        "cwd": "cwd",
        "auto_wakes": "auto wakes",
        "settings": "settings",
        "plugin": "plugin",
        "none": "none",
        "no_other": "none",
        "more_n": "and {n} more (stale markers)",
        "state_off": "off (this session)",
        "state_set": "/cn:set override · {n} left",
        "state_auto": "auto · {n} left",
        "state_no_window": "cannot wake (interval ≥ ttl)",
        "woken_value": "{n}× (this away)",
        "auto_per_away": "{n} per away",
        "auto_disabled": "off",
        "settings_value": "interval {i}m · ttl {t}m",
        "obsolete_warn": "⚠️  {n} obsolete setting(s) ignored — cleaned on /cn:config save",
    },
    "ja": {
        "title": "🔮 cache-necromancer",
        "current_session": "セッション (現在)",
        "other_sessions": "他のセッション",
        "status": "状態",
        "sid": "sid",
        "wake": "延長",
        "woken": "蘇生",
        "next_wake": "次回延長",
        "alive_until": "キャッシュ最大",
        "expired": "既に期限切れ — 次の離席から",
        "prompt": "prompt",
        "cwd": "ディレクトリ",
        "auto_wakes": "自動延長",
        "settings": "設定",
        "plugin": "plugin",
        "none": "なし",
        "no_other": "なし",
        "more_n": "他 {n} 件 (古い stale marker)",
        "state_off": "オフ (このセッション)",
        "state_set": "/cn:set 上書き · 残り{n}回",
        "state_auto": "自動 · 残り{n}回",
        "state_no_window": "延長不可 (interval ≥ ttl)",
        "woken_value": "{n}回 (今回の離席)",
        "auto_per_away": "離席ごとに{n}回",
        "auto_disabled": "オフ",
        "settings_value": "interval {i}分 · ttl {t}分",
        "obsolete_warn": "⚠️  無視される旧設定 {n}件 — /cn:config 保存時に整理",
    },
    "zh": {
        "title": "🔮 cache-necromancer",
        "current_session": "会话 (当前)",
        "other_sessions": "其他会话",
        "status": "状态",
        "sid": "sid",
        "wake": "唤醒",
        "woken": "已复活",
        "next_wake": "下次唤醒",
        "alive_until": "缓存至",
        "expired": "已过期 — 下次离开起",
        "prompt": "prompt",
        "cwd": "目录",
        "auto_wakes": "自动唤醒",
        "settings": "设置",
        "plugin": "plugin",
        "none": "无",
        "no_other": "无",
        "more_n": "另有 {n} 个 (过期 stale marker)",
        "state_off": "已关闭 (本会话)",
        "state_set": "/cn:set 覆盖 · 剩余 {n} 次",
        "state_auto": "自动 · 剩余 {n} 次",
        "state_no_window": "无法唤醒 (interval ≥ ttl)",
        "woken_value": "{n} 次 (本次离开)",
        "auto_per_away": "每次离开 {n} 次",
        "auto_disabled": "关闭",
        "settings_value": "interval {i}分钟 · ttl {t}分钟",
        "obsolete_warn": "⚠️  已忽略 {n} 个旧设置 — /cn:config 保存时清理",
    },
}


def status_label(lang: Language, key: str) -> str:
    """STATUS_LABELS lookup. 없으면 en fallback, 그래도 없으면 key 그대로."""
    return STATUS_LABELS.get(lang, STATUS_LABELS["en"]).get(
        key, STATUS_LABELS["en"].get(key, key)
    )


# /cn:set 응답 문구 ({n}=충전/잔여, {max}=상한, {until}=until_time·until_expired, {time}=캐시 생존 시각 HH:MM)
SET_LABELS: dict[Language, dict[str, str]] = {
    "ko": {
        "status_off": "깨우기 꺼짐 (이 세션) — /cn:set N 또는 auto(패널 [자동])로 다시 켜기",
        "status_set": "이번 자리비움 깨우기 {n}회 남음 — {until}",
        "status_auto": "자동 깨우기 {n}회 남음 — {until}",
        "status_auto_disabled": "자동 깨우기 꺼짐 (설정 auto_wakes = 0) — /cn:set N 으로 이번만 켜기",
        "turned_off": "이 세션 깨우기를 껐어요 (세션 끝까지). 다시 켜려면 /cn:set N 또는 auto(패널 [자동])",
        "charged": "이번 자리비움 깨우기 {n}회 충전 — {until}",
        "capped_note": "최대 {max}회까지만 충전돼요",
        "session_only": "이 세션에만 적용 — 다른 세션은 각자 /cn:set",
        "usage": "사용법: /cn:set N (N회 깨우기) · /cn:set 2h·90m·18:00 (그때까지 살리기) · "
                 "/cn:set auto (자동으로) · /cn:set 0 또는 off (이 세션 끄기) · /cn:set (상태)",
        "back_to_auto": "자동 깨우기로 되돌렸어요 (덮어쓰기·끄기 해제)",
        "already_alive": "캐시가 이미 {time}까지 살아 있어요 — 충전하지 않았어요",
        "no_live_cache": "지금 살아 있는 캐시가 없어요 (만료됐거나 아직 없음) — 충전하지 않았어요",
        "no_window": "깨울 수 없어요 — refresh_interval_minutes 가 cache_ttl_minutes 이상 (설정 확인)",
        "save_failed": "⚠️  marker 저장 실패 — 적용되지 않았어요. 다시 시도하세요.",
        "until_time": "캐시 최대 {time}까지",
        "until_expired": "지금 캐시는 이미 만료 — 다음 자리비움부터 적용",
        "no_session": "session_id 없음 — 채팅 세션 안에서 실행하세요.",
    },
    "en": {
        "status_off": "Wake off (this session) — /cn:set N or auto (panel [Auto]) to turn it back on",
        "status_set": "{n} wake(s) left for this away — {until}",
        "status_auto": "{n} auto wake(s) left — {until}",
        "status_auto_disabled": "Auto wake off (config auto_wakes = 0) — /cn:set N to enable for this away",
        "turned_off": "Wake turned off for this session (until it ends). /cn:set N or auto (panel [Auto]) to turn it back on",
        "charged": "Charged {n} wake(s) for this away — {until}",
        "capped_note": "Capped at {max} wakes",
        "session_only": "This session only — run /cn:set in other sessions separately",
        "usage": "Usage: /cn:set N (N wakes) · /cn:set 2h·90m·18:00 (keep alive until then) · "
                 "/cn:set auto (back to auto) · /cn:set 0 or off (turn off for this session) · /cn:set (status)",
        "back_to_auto": "Back to auto wake (override and off cleared)",
        "already_alive": "Cache is already alive until {time} — nothing charged",
        "no_live_cache": "No live cache right now (expired or not yet created) — nothing charged",
        "no_window": "Cannot wake — refresh_interval_minutes is not below cache_ttl_minutes (check settings)",
        "save_failed": "⚠️  marker save failed — not applied. Please try again.",
        "until_time": "cache alive until {time} at most",
        "until_expired": "cache already expired — applies from the next away",
        "no_session": "No session_id — run inside a chat session.",
    },
    "ja": {
        "status_off": "延長オフ (このセッション) — /cn:set N または auto (パネル [自動]) で再開",
        "status_set": "今回の離席の延長 残り{n}回 — {until}",
        "status_auto": "自動延長 残り{n}回 — {until}",
        "status_auto_disabled": "自動延長オフ (設定 auto_wakes = 0) — /cn:set N で今回だけ有効",
        "turned_off": "このセッションの延長をオフにしました (セッション終了まで)。再開は /cn:set N または auto (パネル [自動])",
        "charged": "今回の離席の延長 {n}回チャージ — {until}",
        "capped_note": "最大{max}回までチャージされます",
        "session_only": "このセッションのみ — 他のセッションは個別に /cn:set",
        "usage": "使い方: /cn:set N (N回延長) · /cn:set 2h·90m·18:00 (その時刻まで維持) · "
                 "/cn:set auto (自動に戻す) · /cn:set 0 または off (このセッションをオフ) · /cn:set (状態)",
        "back_to_auto": "自動延長に戻しました (上書き・オフを解除)",
        "already_alive": "キャッシュは既に{time}まで有効 — チャージしませんでした",
        "no_live_cache": "現在有効なキャッシュがありません (期限切れまたは未作成) — チャージしませんでした",
        "no_window": "延長できません — refresh_interval_minutes が cache_ttl_minutes 以上 (設定を確認)",
        "save_failed": "⚠️  marker 保存失敗 — 適用されていません。再試行してください。",
        "until_time": "キャッシュ最大{time}まで",
        "until_expired": "キャッシュは既に期限切れ — 次の離席から適用",
        "no_session": "session_id なし — チャットセッション内で実行してください。",
    },
    "zh": {
        "status_off": "唤醒已关闭 (本会话) — 用 /cn:set N 或 auto (面板 [自动]) 重新开启",
        "status_set": "本次离开还剩 {n} 次唤醒 — {until}",
        "status_auto": "自动唤醒还剩 {n} 次 — {until}",
        "status_auto_disabled": "自动唤醒已关闭 (设置 auto_wakes = 0) — 用 /cn:set N 仅本次开启",
        "turned_off": "已关闭本会话的唤醒 (直到会话结束)。重新开启: /cn:set N 或 auto (面板 [自动])",
        "charged": "本次离开已充值 {n} 次唤醒 — {until}",
        "capped_note": "最多只能充值 {max} 次",
        "session_only": "仅本会话 — 其他会话需各自 /cn:set",
        "usage": "用法: /cn:set N (唤醒 N 次) · /cn:set 2h·90m·18:00 (保活到那时) · "
                 "/cn:set auto (恢复自动) · /cn:set 0 或 off (关闭本会话) · /cn:set (状态)",
        "back_to_auto": "已恢复自动唤醒 (解除覆盖和关闭)",
        "already_alive": "缓存已存活至 {time} — 未充值",
        "no_live_cache": "当前没有存活的缓存 (已过期或尚未创建) — 未充值",
        "no_window": "无法唤醒 — refresh_interval_minutes 不小于 cache_ttl_minutes (请检查设置)",
        "save_failed": "⚠️  marker 保存失败 — 未生效, 请重试。",
        "until_time": "缓存最长至 {time}",
        "until_expired": "缓存已过期 — 下次离开起生效",
        "no_session": "无 session_id — 请在聊天会话中运行。",
    },
}


def set_label(lang: Language, key: str) -> str:
    """SET_LABELS lookup. 없으면 en fallback, 그래도 없으면 key 그대로."""
    return SET_LABELS.get(lang, SET_LABELS["en"]).get(
        key, SET_LABELS["en"].get(key, key)
    )

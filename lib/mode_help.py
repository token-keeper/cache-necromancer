"""mode 별 한 줄 라벨 + 멀티라인 안내 — /cn:status / /cn:config / /cn:dry-run 공유."""
from __future__ import annotations


def mode_label(mode: str, config) -> str:
    """현재 mode 한 줄 — emoji + 동작 요약 (v0.3.0)."""
    if mode == "notify":
        return "🔔 notify — 알림만 (wake 안 함, cache 갱신 효과 0)"
    if mode == "auto":
        return "⚡ auto — sleep 후 자동 wake (chat 세션 self-wake)"
    if mode == "hybrid":
        return (
            f"💀 hybrid — sleep 후 알림 → {config.refresh.hybrid_wait_seconds}s "
            "동안 입력 없으면 wake (취소 가능)"
        )
    return f"❓ {mode} (알 수 없는 모드)"


def mode_help_text() -> str:
    """3 모드 비교 안내. /cn:config 에서 사용 (v0.3.0)."""
    return (
        "3가지 모드:\n"
        "  🔔 notify — 알림만 (wake 호출 없음, cache 갱신 효과 0)\n"
        "  ⚡ auto   — sleep 후 자동 wake (chat 세션 self-wake)\n"
        "  💀 hybrid — sleep → 알림 → hybrid_wait_seconds 동안 입력 없으면 wake\n"
        "              (사용자가 작업 중이면 취소되어 안전)"
    )


def config_change_hint(config_path) -> str:
    """현재 config.toml 편집 안내 (v0.3.0).

    예시 명령은 printf 사용 — bash single quote 안의 ``\\n`` 은 literal로 들어가
    TOML 줄바꿈이 깨지므로 echo는 부적합.
    """
    return (
        f"설정 변경: {config_path}\n"
        "  편집 후 새 chat 세션부터 적용 (Claude Code 는 settings hot-reload X).\n"
        "예시:\n"
        "  mkdir -p ~/.cache-necromancer\n"
        '  printf \'[general]\\nmode = "auto"\\n\' > ~/.cache-necromancer/config.toml'
    )

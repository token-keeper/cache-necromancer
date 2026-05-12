"""mode 별 한 줄 라벨 + 멀티라인 안내 — /cn:status / /cn:config / /cn:dry-run 공유."""
from __future__ import annotations


def mode_label(mode: str, config) -> str:
    """현재 mode 한 줄 — emoji + 동작 요약."""
    if mode == "notify":
        return "🔔 notify — 알림만 (실제 fire 안 함)"
    if mode == "auto":
        return "⚡ auto — 시점 도달 시 자동 fire (사용자 개입 없음)"
    if mode == "hybrid":
        return (
            f"💀 hybrid — {config.refresh.hybrid_wait_seconds}s 사전 알림 후 "
            "입력 없으면 fire (취소 가능)"
        )
    return f"❓ {mode} (알 수 없는 모드)"


def mode_help_text() -> str:
    """3 모드 비교 안내. /cn:config 에서 사용."""
    return (
        "3가지 모드:\n"
        "  🔔 notify — 알림만 (실제 fire 호출 없음, 비용 0)\n"
        "  ⚡ auto   — 시점 도달 시 자동 fire (무인 자동화)\n"
        "  💀 hybrid — 사전 알림 후 hybrid_wait_seconds 동안 입력 없으면 fire\n"
        "              (사용자가 작업 중이면 취소되어 안전)"
    )


def config_change_hint(config_path) -> str:
    """현재 config.toml 편집 안내."""
    return (
        f"설정 변경: {config_path}\n"
        "  편집 후 다음 Stop hook 부터 적용. 데몬 재시작 필요 없음.\n"
        "예시:\n"
        '  echo \'[general]\\nmode = "auto"\' > ~/.cache-necromancer/config.toml'
    )

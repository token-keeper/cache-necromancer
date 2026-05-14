"""TOML config 로드.

기본값은 dataclass field에 명시. 누락된 키는 기본값 유지.
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VALID_MODES: tuple[str, ...] = ("notify", "auto", "hybrid")


@dataclass(frozen=True)
class RefreshConfig:
    prompt: str = "."
    hybrid_wait_seconds: int = 60
    fire_timeout_seconds: int = 240


@dataclass(frozen=True)
class NotifyConfig:
    terminal_bell: bool = True
    system_notification: bool = True
    imminent_threshold_minutes: int = 5


@dataclass(frozen=True)
class AdvancedConfig:
    daemon_poll_max_seconds: int = 60
    session_ttl_hours: int = 24
    daemon_idle_shutdown_minutes: int = 60
    clock_drift_threshold_seconds: int = 30
    clock_drift_postpone_minutes: int = 5
    fire_stop_watchdog_seconds: int = 120
    consecutive_fire_failures_disable: int = 5
    cache_cold_max_retries: int = 2
    backoff_base_seconds: float = 30.0
    backoff_cap_seconds: float = 1800.0
    interactive_input_quiet_seconds: int = 30
    state_lock_deadline_seconds: float = 4.0


@dataclass(frozen=True)
class Config:
    mode: Literal["notify", "auto", "hybrid"] = "hybrid"
    refresh_interval_minutes: int = 55
    max_refresh_count: int = 10
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)


def _env_mode_override() -> str | None:
    """Claude Code userConfig 가 주입하는 환경변수.

    빈 문자열은 무시 (= override 없음). 잘못된 값은 호출자가 검증.
    """
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_MODE")
    return v if v else None


def load_config(path: Path) -> Config:
    """TOML 파일에서 Config 로드. 없으면 기본값.

    Raises:
        ValueError: ``mode`` 가 유효하지 않은 경우.
    """
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = {}
    general = data.get("general", {})
    mode = general.get("mode", "hybrid")
    if mode not in VALID_MODES:
        raise ValueError(
            f"invalid mode: {mode}. Must be one of {VALID_MODES}"
        )
    return Config(
        mode=mode,
        refresh_interval_minutes=general.get("refresh_interval_minutes", 55),
        max_refresh_count=general.get("max_refresh_count", 10),
        refresh=RefreshConfig(**data.get("refresh", {})),
        notify=NotifyConfig(**data.get("notify", {})),
        advanced=AdvancedConfig(**data.get("advanced", {})),
    )


_DEFAULT_TEMPLATE = """# cache-necromancer 설정 — `/cn:config` 로 모드 비교 가능
# 이 파일은 첫 데몬 spawn 시 자동 생성됨. 수정 후 데몬 재시작 필요.

[general]
mode = "{mode}"                       # notify | auto | hybrid
refresh_interval_minutes = 55
max_refresh_count = 10

[refresh]
prompt = "."
hybrid_wait_seconds = 60
fire_timeout_seconds = 240

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = 5

# [advanced] — 고급 옵션은 docs/superpowers/specs/...-design-v5.md 참조
"""


def ensure_config_file(path: Path) -> None:
    """파일이 없으면 기본 템플릿 작성. 있으면 그대로 둔다 (사용자 편집 보존).

    템플릿의 [general].mode 는 환경변수 ``CLAUDE_PLUGIN_OPTION_MODE`` 가
    valid mode 일 때만 그 값으로, 아니면 ``hybrid`` 로 채운다.
    """
    if path.exists():
        return
    env_mode = _env_mode_override()
    mode = env_mode if env_mode in VALID_MODES else "hybrid"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_TEMPLATE.format(mode=mode), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

"""TOML config 로드 (v0.3.0).

기본값은 dataclass field 에 명시. 누락된 키는 기본값 유지.
v0.2.x 의 폐기 옵션 (terminal_bell, imminent_threshold_minutes,
refresh.prompt, refresh.fire_timeout_seconds, [advanced] 전체) 은
detect 시 stderr 경고만 출력하고 무시.
"""
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VALID_MODES: tuple[str, ...] = ("notify", "auto", "hybrid")

_KNOWN_REFRESH_KEYS = {"hybrid_wait_seconds"}
_KNOWN_NOTIFY_KEYS = {"system_notification"}
_DEPRECATED_REFRESH = {"prompt", "fire_timeout_seconds"}
_DEPRECATED_NOTIFY = {"terminal_bell", "imminent_threshold_minutes"}


@dataclass(frozen=True)
class RefreshConfig:
    hybrid_wait_seconds: int = 60


@dataclass(frozen=True)
class NotifyConfig:
    system_notification: bool = True


@dataclass(frozen=True)
class Config:
    mode: Literal["notify", "auto", "hybrid"] = "hybrid"
    refresh_interval_minutes: int = 50  # v0.2.x 55 → 50 (1h cache + 안전 마진)
    max_refresh_count: int = 10
    language: str = "en"  # ko | en | ja | zh (validate 는 lib.i18n.normalize_language)
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env_mode_override() -> str | None:
    """Claude Code userConfig 가 주입하는 환경변수.

    빈 문자열은 무시 (= override 없음). 잘못된 값은 호출자가 검증.
    """
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_MODE")
    return v if v else None


def detect_deprecated_keys(data: dict) -> list[str]:
    """v0.2.x 의 폐기된 옵션 list 반환. load_config + cn_status 양쪽이 공유.

    Returns:
        ["refresh.prompt", "[advanced] (keys: ...)", ...] 형식.
    """
    found: list[str] = []
    for key in data.get("refresh", {}):
        if key in _DEPRECATED_REFRESH:
            found.append(f"refresh.{key}")
    for key in data.get("notify", {}):
        if key in _DEPRECATED_NOTIFY:
            found.append(f"notify.{key}")
    if "advanced" in data:
        adv_keys = ", ".join(sorted(data["advanced"].keys())) or "(빈 섹션)"
        found.append(f"[advanced] (전체 섹션 — keys: {adv_keys})")
    return found


def _warn_deprecated(data: dict) -> None:
    """v0.2.x 폐기 옵션 detect 시 stderr 경고 (load 자체는 성공)."""
    found = detect_deprecated_keys(data)
    if found:
        print(
            "[cn:warn] deprecated v0.2.x config 옵션 감지 (v0.3.0 에서 폐기, 무시): "
            + ", ".join(found),
            file=sys.stderr,
        )


def parse_config_file(path: Path) -> tuple[dict, str | None]:
    """TOML 파일 raw parse. (data, error_msg) 반환. 파일 없으면 ({}, None).

    cn_status 가 deprecated detect 만 위해 load_config 의 side effect 를 피하고
    싶을 때 사용.
    """
    if not path.exists():
        return {}, None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f), None
    except tomllib.TOMLDecodeError as e:
        return {}, str(e)
    except OSError as e:
        return {}, str(e)


def load_config(path: Path) -> Config:
    """TOML 파일에서 Config 로드. 없거나 syntax error 시 기본값.

    Raises:
        ValueError: ``mode`` 가 유효하지 않은 경우.
    """
    if path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(
                f"[cn:warn] config.toml syntax error: {e}. 기본값 사용.",
                file=sys.stderr,
            )
            data = {}
    else:
        data = {}

    _warn_deprecated(data)

    general = data.get("general", {})
    mode = general.get("mode", "hybrid")
    if mode not in VALID_MODES:
        raise ValueError(
            f"invalid mode: {mode}. Must be one of {VALID_MODES}"
        )

    # 알려진 옵션만 추출 (폐기 옵션은 무시)
    refresh_data = {
        k: v for k, v in data.get("refresh", {}).items() if k in _KNOWN_REFRESH_KEYS
    }
    notify_data = {
        k: v for k, v in data.get("notify", {}).items() if k in _KNOWN_NOTIFY_KEYS
    }

    return Config(
        mode=mode,
        refresh_interval_minutes=general.get("refresh_interval_minutes", 50),
        max_refresh_count=general.get("max_refresh_count", 10),
        language=general.get("language", "en"),
        refresh=RefreshConfig(**refresh_data),
        notify=NotifyConfig(**notify_data),
    )


_DEFAULT_TEMPLATE = """# cache-necromancer 설정 (v0.3.0)
# 이 파일은 첫 hook fire 시 자동 생성됨.
# 수정 후 새 chat 세션 필요 (Claude Code 는 settings hot-reload 안 함).

[general]
mode = "{mode}"                       # notify | auto | hybrid
refresh_interval_minutes = 50         # cache TTL 만료 직전 (1h cache 기준)
max_refresh_count = 10                # 한 세션 최대 wake/notify 횟수
language = "en"                       # recap 메시지 언어: ko | en | ja | zh

[notify]
system_notification = true            # macOS osascript 알림

[refresh]
hybrid_wait_seconds = 60              # hybrid 모드 알림 후 사용자 input 대기
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

"""TOML config 로드 (v0.12.0 — 자리비움마다 자동 깨우기 N회 하나로 통합).

키 5개 (`[general] auto_wakes·refresh_interval_minutes·cache_ttl_minutes·language`,
`[display] countdown`). 옛 키(arm·notify·grace·max_refresh_count 등)는 경고 없이
무시하고 /cn:status 에만 한 줄 표시한다 (`detect_obsolete_keys`).

잘못된 값(타입·범위 밖)은 그 키만 기본값 + stderr 경고. TOML 문법 오류는 전체 기본값.
"""
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# /cn:set N 충전 상한 — 설정이 아니라 코드 상수
SET_CAP: int = 10

# 무시되는 옛 키. "section.*" 는 섹션 전체.
OBSOLETE_KEYS: tuple[str, ...] = (
    "general.mode",
    "general.max_refresh_count",
    "wake.*",
    "notify.*",
    "refresh.*",
    "advanced.*",
    "display.recap_style",
)

_LANGUAGES: tuple[str, ...] = ("ko", "en", "ja", "zh")


@dataclass(frozen=True)
class DisplayConfig:
    """표시 설정."""

    countdown: bool = True  # 입력창 아래 띠의 캐시 카운트다운 (mod — hooks/register.tsx 가 읽음)


@dataclass(frozen=True)
class Config:
    """플러그인 전역 설정."""

    refresh_interval_minutes: int = 50  # 캐시 마지막 적중 뒤 이만큼 지나면 깨우기
    cache_ttl_minutes: int = 60         # 캐시 수명 (1h ext cache)
    auto_wakes: int = 2                 # 자리비움마다 자동 깨우기 최대 횟수 (0 = 안 깨움)
    language: str = "en"                # ko | en | ja | zh
    display: DisplayConfig = field(default_factory=DisplayConfig)


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def detect_obsolete_keys(data: dict) -> list[str]:
    """파일에 실제 있는 옛 키 목록 ("wake.arm" 처럼 키 단위)."""
    found: list[str] = []
    for pattern in OBSOLETE_KEYS:
        section, key = pattern.split(".", 1)
        if section not in data:
            continue
        table = data[section]
        if not isinstance(table, dict):
            if key == "*":
                found.append(section)
            continue
        if key == "*":
            found.extend(f"{section}.{k}" for k in table)
        elif key in table:
            found.append(pattern)
    return found


def parse_config_file(path: Path) -> tuple[dict, str | None]:
    """TOML 파일 raw parse. (data, error_msg) 반환. 파일 없으면 ({}, None)."""
    if not path.exists():
        return {}, None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f), None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:  # 비 UTF-8 파일도 기본값
        return {}, str(e)
    except OSError as e:
        return {}, str(e)


def _warn_invalid(name: str, value: object, default: object) -> None:
    print(f"[cn:warn] invalid {name}: {value!r} — 기본값 {default!r}", file=sys.stderr)


def _int_in(table: dict, section: str, key: str, default: int,
            lo: int, hi: int | None = None) -> int:
    """정수 lo~hi 면 그 값, 없으면 기본값, 잘못됐으면 경고 + 기본값. bool 은 정수로 안 친다."""
    if key not in table:
        return default
    value = table[key]
    if (isinstance(value, int) and not isinstance(value, bool)
            and value >= lo and (hi is None or value <= hi)):
        return value
    _warn_invalid(f"{section}.{key}", value, default)
    return default


def load_config(path: Path) -> Config:
    """TOML 파일에서 Config 로드. 없거나 syntax error 시 기본값. 예외를 던지지 않는다."""
    data, err = parse_config_file(path)
    if err is not None:
        print(f"[cn:warn] config.toml syntax error: {err}. 기본값 사용.", file=sys.stderr)

    d = Config()
    general = _section(data, "general")
    display_data = _section(data, "display")

    language = general.get("language", d.language)
    if language not in _LANGUAGES:
        _warn_invalid("general.language", language, d.language)
        language = d.language

    countdown = display_data.get("countdown", d.display.countdown)
    if not isinstance(countdown, bool):
        _warn_invalid("display.countdown", countdown, d.display.countdown)
        countdown = d.display.countdown

    return Config(
        refresh_interval_minutes=_int_in(
            general, "general", "refresh_interval_minutes", d.refresh_interval_minutes, 1),
        cache_ttl_minutes=_int_in(
            general, "general", "cache_ttl_minutes", d.cache_ttl_minutes, 1),
        auto_wakes=_int_in(general, "general", "auto_wakes", d.auto_wakes, 0, SET_CAP),
        language=language,
        display=DisplayConfig(countdown=countdown),
    )


_DEFAULT_TEMPLATE = """# cache-necromancer 설정 (v0.12.0)
# 이 파일은 첫 hook 실행 시 자동 생성됨.
# 깨우기 판정·/cn:set·/cn:status 는 다음 판정부터 바로, 입력창 아래 띠와 깨우기 시점(mod)은 새 세션부터 바뀐 값을 쓴다.

[general]
auto_wakes = 2                        # 자리비움마다 자동 깨우기 최대 횟수 (0 = 깨우지 않음, 최대 10)
refresh_interval_minutes = 50         # 캐시 마지막 적중 뒤 이만큼 지나면 깨우기
cache_ttl_minutes = 60                # 캐시 수명 (띠 카운트다운·생존 시각 기준)
language = "en"                       # 메시지 언어: ko | en | ja | zh

[display]
countdown = true                      # 입력창 아래 띠에 캐시 남은 시간 카운트다운 (Claude Code v2.1.286+)
"""


def ensure_config_file(path: Path) -> None:
    """파일이 없으면 기본 템플릿 작성. 있으면 그대로 둔다 (사용자 편집 보존)."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_TEMPLATE, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

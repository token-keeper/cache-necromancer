"""TOML config 로드 (v0.5.0 — 2축: notify + wake).

v0.5.0 부터 mode enum (notify/auto/hybrid) 대신 두 독립 축으로 동작:
  - [notify] enabled: 만료 임박 알림 on/off
  - [wake] arm ("manual"|"always"), grace_seconds: 소생 정책

v0.4.x 이하 legacy 키 (general.mode, notify.system_notification,
refresh.hybrid_wait_seconds) 는 로드 시 자동 매핑되므로 기존 설정 파일 그대로 동작.
신 키가 있으면 legacy 보다 우선.

v0.2.x 의 폐기 옵션 (terminal_bell, imminent_threshold_minutes,
refresh.prompt, refresh.fire_timeout_seconds, [advanced] 전체) 은
detect 시 stderr 경고만 출력하고 무시.

임시 호환 property (Task 9 에서 제거):
  - Config.mode: wake.arm + notify.enabled → legacy mode 문자열 역매핑
  - Config.refresh: RefreshConfig(hybrid_wait_seconds=wake.grace_seconds)
  - NotifyConfig.system_notification: notify.enabled alias
"""
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_ARMS: tuple[str, ...] = ("manual", "always")
_LEGACY_MODES: tuple[str, ...] = ("notify", "auto", "hybrid")

# v0.4.x 이하 legacy 키 — 로드 시 매핑, /cn:status 경고용
_LEGACY_GENERAL = {"mode"}
_LEGACY_NOTIFY = {"system_notification"}
_LEGACY_REFRESH = {"hybrid_wait_seconds"}

_DEPRECATED_REFRESH = {"prompt", "fire_timeout_seconds"}
_DEPRECATED_NOTIFY = {"terminal_bell", "imminent_threshold_minutes"}


@dataclass(frozen=True)
class WakeConfig:
    """소생 정책 설정."""

    arm: str = "manual"
    grace_seconds: int = 60


@dataclass(frozen=True)
class NotifyConfig:
    """알림 설정."""

    enabled: bool = True

    # ── 임시 호환 property (Task 9 에서 제거) ──
    @property
    def system_notification(self) -> bool:
        """scripts/refresh.py 호환용 alias → self.enabled."""
        return self.enabled


@dataclass(frozen=True)
class RefreshConfig:
    """임시 호환 dataclass (Task 9 제거): config.refresh.hybrid_wait_seconds."""

    hybrid_wait_seconds: int = 60


@dataclass(frozen=True)
class Config:
    """플러그인 전역 설정."""

    refresh_interval_minutes: int = 50  # v0.2.x 55 → 50 (1h cache + 안전 마진)
    cache_ttl_minutes: int = 60         # Anthropic prompt cache TTL (1h ext cache 기본)
    max_refresh_count: int = 10
    language: str = "en"               # ko | en | ja | zh
    wake: WakeConfig = field(default_factory=WakeConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    # ── 임시 호환 property (Task 9 에서 제거) ──
    @property
    def mode(self) -> str:
        """scripts 호환용 역매핑: wake.arm + notify.enabled → legacy mode 문자열.

        엣지: arm=manual + enabled=False 는 v0.4.x 에 없던 신규 상태 —
        "notify" 를 반환하지만 _do_notify 의 no-op 경로로 runtime 동작은 정확.
        Task 9 에서 제거 예정.
        """
        if self.wake.arm == "always":
            return "hybrid" if self.notify.enabled else "auto"
        return "notify"

    @property
    def refresh(self) -> RefreshConfig:
        """scripts 호환용: config.refresh.hybrid_wait_seconds → wake.grace_seconds."""
        return RefreshConfig(hybrid_wait_seconds=self.wake.grace_seconds)


def detect_legacy_keys(data: dict) -> list[str]:
    """v0.4.x 이하 legacy 키 목록 반환 (매핑은 되지만 /cn:status 에서 경고)."""
    found: list[str] = []
    for key in data.get("general", {}):
        if key in _LEGACY_GENERAL:
            found.append(f"general.{key}")
    for key in data.get("notify", {}):
        if key in _LEGACY_NOTIFY:
            found.append(f"notify.{key}")
    for key in data.get("refresh", {}):
        if key in _LEGACY_REFRESH:
            found.append(f"refresh.{key}")
    return found


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


def _resolve_axes(data: dict) -> tuple[WakeConfig, NotifyConfig]:
    """신 키 우선, 없으면 legacy 매핑 (spec §3.4), 그것도 없으면 기본값.

    legacy 매핑 규칙:
      - mode=hybrid  → arm=always, enabled=True  (system_notification 반영)
      - mode=auto    → arm=always, enabled=False  (알림 없이 즉시 wake)
      - mode=notify  → arm=manual, enabled=True   (system_notification 반영)
      - hybrid_wait_seconds → grace_seconds
      - system_notification (hybrid/notify 에서만) → enabled
    """
    general = data.get("general", {})
    wake_data = data.get("wake", {})
    notify_data = data.get("notify", {})

    # legacy mode 해석
    legacy_arm: str | None = None
    legacy_enabled: bool | None = None
    mode = general.get("mode")
    if mode is not None:
        if mode in _LEGACY_MODES:
            legacy_arm = "always" if mode in ("hybrid", "auto") else "manual"
            # 구 auto 는 system_notification 과 무관하게 알림 없이 즉시 wake
            legacy_enabled = mode != "auto"
        else:
            print(
                f"[cn:warn] invalid legacy mode: {mode!r} — 무시 (기본값 사용)",
                file=sys.stderr,
            )
    # system_notification: auto 에서는 이미 False 로 고정 — 덮어쓰지 않음
    if legacy_enabled is not False and "system_notification" in notify_data:
        legacy_enabled = bool(notify_data["system_notification"])
    legacy_grace = data.get("refresh", {}).get("hybrid_wait_seconds")

    # 신 키 우선
    arm = wake_data.get("arm", legacy_arm if legacy_arm is not None else "manual")
    if arm not in VALID_ARMS:
        print(
            f"[cn:warn] invalid wake.arm: {arm!r} — fallback to 'manual'",
            file=sys.stderr,
        )
        arm = "manual"
    grace = wake_data.get(
        "grace_seconds", legacy_grace if legacy_grace is not None else 60
    )
    enabled = notify_data.get(
        "enabled", legacy_enabled if legacy_enabled is not None else True
    )
    return WakeConfig(arm=arm, grace_seconds=int(grace)), NotifyConfig(
        enabled=bool(enabled)
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

    v0.5.0: mode enum 대신 2축(notify/wake). legacy 키는 자동 매핑.
    invalid mode/arm 은 stderr 경고 후 기본값 사용.

    Raises:
        ValueError: grace_seconds 가 정수 변환 불가한 값일 때 (예: "abc")
            전파. 호출자 처리 — refresh.py/on_recap.py 가 catch.
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
    wake, notify = _resolve_axes(data)
    return Config(
        refresh_interval_minutes=general.get("refresh_interval_minutes", 50),
        cache_ttl_minutes=general.get("cache_ttl_minutes", 60),
        max_refresh_count=general.get("max_refresh_count", 10),
        language=general.get("language", "en"),
        wake=wake,
        notify=notify,
    )


_DEFAULT_TEMPLATE = """# cache-necromancer 설정 (v0.5.0)
# 이 파일은 첫 hook fire 시 자동 생성됨.
# 수정 후 새 chat 세션 필요 (Claude Code 는 settings hot-reload 안 함).

[general]
refresh_interval_minutes = 50         # cache TTL 만료 직전 알림/wake 까지의 sleep
cache_ttl_minutes = 60                # Anthropic prompt cache TTL (recap 표시용)
max_refresh_count = 10                # wake 상한 (always 연쇄 / set 1회 충전 상한)
language = "en"                       # 메시지 언어: ko | en | ja | zh

[notify]
enabled = true                        # 만료 임박 macOS 알림

[wake]
arm = "manual"                        # manual = /cn:set 시에만 소생 / always = 매 turn 자동
grace_seconds = 60                    # 알림 후 wake 까지 대기 (notify.enabled=true 일 때)
"""


def ensure_config_file(path: Path) -> None:
    """파일이 없으면 기본 템플릿 작성. 있으면 그대로 둔다 (사용자 편집 보존).

    v0.5.0: CLAUDE_PLUGIN_OPTION_MODE 시드 제거 — 신규 설치는 항상 manual 기본
    (codex 리뷰 F3: legacy hybrid 시드 → arm=always 격상 사고 방지).
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_TEMPLATE, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

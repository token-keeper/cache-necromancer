# Changelog

이 프로젝트의 모든 주목할 만한 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따르고, [Semantic Versioning](https://semver.org/lang/ko/) 을 준수합니다.

## [0.1.1] — 2026-05-13

v0.1.0 alpha 도그푸딩 첫 라운드에서 발견된 onboarding 마찰 4건 보완.

### Added

- **`userConfig` (mode)** — `/plugin install` 시점에 모드(notify/auto/hybrid) 선택 프롬프트.
- **config.toml 자동 생성** — 첫 데몬 spawn 시 `~/.cache-necromancer/config.toml` 이 없으면 기본 템플릿 생성. 이미 있으면 절대 덮어쓰지 않음 (사용자 편집 보존).
- **`CLAUDE_PLUGIN_OPTION_MODE` 환경변수** — `/plugin install` 시 선택한 모드를 첫 `config.toml` 템플릿 생성에 1회 반영. 이후 `config.toml` 이 권위.

### Fixed

- **`/cn:dry-run` 과 `/cn:status` 출력에서 UUID 형식 session_id 원본 노출** — `sid_hash[:8]` 짧은 마스크로 표시 (transcript 캡처 노출 보호). 파일시스템 / 상태 비교는 원본 sid_hash 유지.

## [0.1.0] — 2026-05-13

초기 공개 릴리스 (alpha).

### Added

- **Headless CLI 기반 자동 캐시 갱신** — `claude -p "." --resume <sid> --fork-session --no-session-persistence --output-format json` 로 캐시 TTL 리셋. 원본 transcript 무변경.
- **3 작동 모드**:
  - `notify` — 시점 알림만 (실제 fire 없음)
  - `auto` — 자동 fire
  - `hybrid` (기본) — 60초 사전 알림 후 입력 없으면 fire
- **세션 추적**: Stop / UserPromptSubmit / SessionEnd hook 3종으로 세션별 state 파일 관리 (atomic write + flock + 권한 0600).
- **단일 인스턴스 데몬**: lockfile + PID/start_time 검증으로 중복 spawn 방지. Stop hook 이 lazy spawn.
- **동적 폴링 + drift 보정**: 다음 fire 시점에 맞춰 sleep, monotonic clock drift 감지 시 next_refresh_at 5분 미룸.
- **FireReason 7종 분기**: OK / CACHE_COLD / NETWORK_ERROR / AUTH_ERROR / PROCESS_ERROR / TIMEOUT / BAD_OUTPUT — 각 분기별 적절한 backoff / disable / retry 처리.
- **Exponential backoff with jitter** (base 30s, cap 30min, ±25%) — 5회 연속 실패 시 disabled, 3회 연속 시 알림.
- **CACHE_COLD 1회 retry 허용 → 2회 누적 시 영구 disable**.
- **disabled 마커**: delete 대신 보존 — `/cn:status` 로 원인 확인 가능.
- **fire→Stop watchdog**: 120s 경과 시 next_refresh_at 만 복구 (refresh_count 미변경).
- **Transcript bounded tail**: 64KB 끝만 읽어 마지막 assistant usage 추출 (100ms 보장). 과거 turn fallback 차단.
- **user_turn log**: after_fire 판정 포함 — Phase 4 대시보드용 raw data.
- **슬래시 명령**:
  - `/cn:status` — 데몬 / 세션 / 24h fire 통계 표시 (현재 세션 `(this)` 마킹)
  - `/cn:dry-run` — 다음 fire 시점 시뮬레이션 (session_id 마스킹 출력)
- **민감정보 미기록**: 모든 log 는 sid_hash + token 수만. 7일 자동 회전.
- **macOS 알림 + 터미널 bell**: imminent (만료 5분 전) + 후보 도달 + 3회 실패.

### Security

- State 파일 0600 / 디렉토리 0700 권한 강제
- session_id sanitize (`\A[a-zA-Z0-9_-]{1,64}\Z`)
- corrupt JSON 자동 격리 (`.corrupt.<timestamp>` 으로 이동 후 새 state 시작)
- dry-run 출력에서 session_id 마스킹 (`<sid:abc12345>`)

### Notes

- 공식 권장 사용 패턴 아님 — Anthropic 캐시 정책 회색지대. 개인 사용 목적.
- alpha 단계 — 실사용 피드백 받는 중. 자동 모드 (auto/hybrid) 는 비용 발생함.
- 기본 max_refresh_count=10 (세션당). 무제한은 `-1`.

# Changelog

이 프로젝트의 모든 주목할 만한 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따르고, [Semantic Versioning](https://semver.org/lang/ko/) 을 준수합니다.

## [0.2.2] — 2026-05-14

v0.2.1 머지 후 도그푸딩에서 드러난 **도구 동작 자체** 의 핵심 결함 보강. fire 가 OK 로 떨어져도 사용자 chat cache 가 갱신되지 않던 근본 원인 (모델 불일치) 과, 사용자가 자리 비운 사이 데몬이 종료되어 cache TTL 이 만료되던 문제.

### Fixed

- **모델 불일치로 인한 cache miss (B)** — `build_fire_command` 가 `--model` 을 명시하지 않아 fire 가 CLI default 모델 (보통 sonnet) 로 호출되는데, 사용자 chat 은 opus 등 다른 모델일 수 있다. Anthropic prompt cache 는 **모델별로 분리**되므로 fire 가 sonnet cache 를 갱신해도 사용자 chat (opus) 에는 무관 → cache_read=0. transcript 의 마지막 assistant turn 에서 model 을 추출해 `--model <model>` 로 명시. 못 찾으면 생략 (CLI default fallback — 도구 죽지 않음).
  - 진단: `b808132d` 세션에 `--model claude-opus-4-7` 명시해 직접 fire → 17.6s 정상 OK 응답 + `modelUsage=['claude-opus-4-7']` 확인. 같은 세션 sonnet fire (cache_read=130069) 와 opus fire (cache_read=19999) 가 별도 cache 임을 직접 확인.
- **idle shutdown 으로 인한 cache TTL 만료 (A)** — `daemon_idle_shutdown_minutes` (default 60분) 가 **사용자 직접 활동** (last_stop_at / last_user_input_at) 기준이라, 사용자가 1시간 자리 비우면 데몬이 종료. 다음 hook 트리거까지 fire 가 안 일어나고 그 사이 cache TTL 1시간이 만료 → 돌아왔을 때 cache_read=0. shutdown 조건을 **"모든 세션이 disabled"** 로 변경. active 세션이 하나라도 있으면 데몬 유지 → fire 일정 보장.
  - `daemon_idle_shutdown_minutes` 설정은 deprecated (코드/config 호환 위해 남김. 실제 사용 안 됨).

### Changed

- **`fire_timeout_seconds` default 120 → 240** — opus + 큰 transcript 의 cache_creation (10만+ tokens) 호출 시간 보강. config 기존 사용자는 본인 값 유지 (자동 변경 없음). v0.3.0 트랙에서 self-resume 충돌 별도 조사 예정.
- **`daemon/poller.py`**: `all_sessions_disabled(sessions)` helper 신규. 기존 `all_stale_for` 는 deprecated 상태로 유지 (외부 호출 없음 + BC 위해 함수 자체는 남김).

### Added

- **`daemon/transcript.py`** 에 `extract_last_assistant_model(transcript_path)` — 64KB tail 안에서 가장 최근 assistant turn 의 `message.model` 추출. 못 찾으면 None. **이전 turn fallback 금지** (모델 바뀐 turn 직후 fire 가 이전 모델로 가는 결함 차단).

### Notes

- **v0.2.2 비용 인지**: `--model` 명시로 사용자 chat 모델 (opus 등) 사용 시 fire 1회 비용이 sonnet 대비 5~10배 비쌀 수 있다. 본 도구의 모든 자동 fire 모드 (auto/hybrid) 는 비용 발생 — 알파 단계 사용자 본인 모니터링 필요. 비용 우려 시 `mode=notify` 로 전환.
- **남은 의문**: `4f3cc9b5` 활성 세션에 self-resume fire 시 180s timeout (다른 sid 17.6s). 같은 sid 의 활성 사용자 세션 ↔ fire 의 lock 충돌 가설. 별도 트랙으로 v0.3.0 또는 v0.2.3 에서 조사.
- pytest: 251 → **267 passed, 1 skipped** (transcript +9, refresh +3, poller +4).
- 운영 권장: 머지 후 데몬 재시작 (`pkill -f "python.*-m daemon" && rm -f ~/.cache-necromancer/daemon.lock`). 다음 hook 에서 fix 코드로 spawn.

## [0.2.1] — 2026-05-14

핵심 fire 기능 복구 — `claude -p --output-format json` 의 실제 응답 형식 (메시지 list) 처리.

### Fixed

- **`bad_output` 폭주** — `claude` CLI 2.1.x 의 `--output-format json` 응답이 **메시지 list** (마지막 element 가 `type: "result"` + `usage`/`modelUsage`) 인데 `daemon/refresh.py` 는 top-level dict 만 처리해 모든 fire 가 `BAD_OUTPUT` 으로 떨어지던 문제. list 응답 시 마지막 `type == "result"` element 를 추출해 기존 usage 파싱 흐름으로 진입.
  - v0.2.0 도그푸딩 24h 동안 fire 25회 전부 실패 (bad_output=21, timeout=4) → 핵심 캐시 갱신 기능 완전 무력화 상태였음.
  - 진단: 실제 `claude` 명령 1회 probe 로 stdout 캡처 → JSON array (length 5, 마지막 result element) 확인.
  - 구버전 호환: top-level dict 응답도 그대로 처리 — 기존 backward-compat 흐름 유지.
- **manual fire 시 stdin 대기 워닝** — `subprocess.run` 에 `stdin=subprocess.DEVNULL` 명시. 데몬 호출에는 영향 없음 (이미 부모 stdin 이 DEVNULL), manual fire / probe 시 `"no stdin data received in 3s"` 워닝 제거.

### Added

- **회귀 가드 테스트 6개** (`tests/daemon/test_refresh.py`):
  - `test_fire_ok_with_list_response_picks_result_element` — list 응답에서 result element 추출 성공
  - `test_fire_cache_cold_with_list_response_and_zero_cache_read` — list 응답이어도 cache_read=0 → CACHE_COLD
  - `test_fire_bad_output_when_list_empty` — `[]` → BAD_OUTPUT
  - `test_fire_bad_output_when_list_has_no_result_element` — result element 없으면 BAD_OUTPUT
  - `test_fire_picks_last_result_when_multiple` — 안전 가드: 여러 result 있으면 마지막 사용
  - `test_fire_bad_output_when_list_contains_non_dict_items` — `[1,2,3]` → BAD_OUTPUT

### Notes

- SemVer: v0.3.0 P0 작업 분리 — 본 patch 는 fire 동작 복구만, 나머지 P1~P3 (cwd 마스킹 정책 / multi-session 자동 정리 / 데몬 started ISO) 는 다음 marker.
- pytest: 245 → **251 passed, 1 skipped** (test_refresh.py 25 → 31).
- 운영 권장: 머지 후 `~/.cache-necromancer/config.toml` 의 `mode` 가 `notify` 로 임시 전환되어 있으면 `hybrid` 로 복귀 + 데몬 재시작 (`pkill -f "python.*-m daemon" && rm ~/.cache-necromancer/daemon.lock`).

## [0.2.0] — 2026-05-14

`/cn:dry-run` 통합 + `/cn:status` 박스 표 디자인 + **hook 기반 turn 0회 메커니즘**.

### Added

- **Turn 0회 `/cn:status`** — `UserPromptExpansion` hook (`scripts/on_status_command.py`) 이 slash command 자체를 차단하고 `cn_status.py` 결과를 `decision: "block"` 의 `reason` 으로 반환. LLM 호출 0회 = API 비용 0. 캐시 절약 도구의 정체성과 일관.
- **박스 표 디자인** — Unicode 박스 그리기 (`┌─│└┘├┼┤`) 로 outer 박스 + nested inner 박스 4종 (데몬 / 세션 / active 세션 디테일 / 최근 24h fires). 헤더 + 모드/설정 안내도 outer 박스 내부.
- **`lib/box_renderer.py`** — 한글 East Asian Width + emoji variation selector (FE0F) 보정한 박스 그리기 모듈. `box_section`, `box_table` (옵션 `row_separator`), `wrap_outer` 제공. 외부 의존성 없음.
- **`last prompt:` 표시** — `UserPromptSubmit` hook 에서 사용자 자연어 prompt 첫 줄 80자 발췌를 state.last_user_prompt_excerpt 로 저장. slash command (`/` 시작) 는 제외. `CN_TRACK_LAST_PROMPT=0` 으로 opt-out.
- **세션 행 사이 가로줄 구분선** — 표 가독성 향상 (`├──┼──┤` 자동 삽입).
- **고정 폭 outer 박스** — `CN_MAX_WIDTH` 환경변수로 조정 (기본 100).
- **README 트러블슈팅**: 다른 프로젝트 세션 자동 추적 동작 설명 + 정리 방법 + 비용 인지.

### Changed

- **`/cn:status` 출력 전체 박스 표 디자인으로 교체** — 세션은 표 (sid · 상태 · next · refresh · warning), 데몬/디테일/24h fires 는 단순 박스.
- **`disabled_at` / `backoff_until` 시간 부분만 표시** — 컬럼 너비 절약. `HH:MM:SS` 형식 (`_short_time` helper).
- **disabled reason `consecutive_failures_` prefix 단축** — `consecutive_failures_bad_output` → `bad_output`.
- **cwd 길이 70자 truncate** — 박스 폭 cap 안에 들어가게.
- **`(this)` 마커 → `*`** — sid 컬럼 뒤에 짧은 마커.
- **active 세션 디테일 박스 구성 변경** — command 줄 제거 (불필요한 정보), 대신 `last prompt:` 추가. cwd + last fire 유지.

### Removed

- **`/cn:dry-run` 명령** — `/cn:status` 가 흡수.
  - 관련 자산 삭제: `commands/cn:dry-run.md`, `scripts/cn_dry_run.py`, `tests/scripts/test_cn_dry_run.py`.
- **`scripts/cn_status.py` 의 `_redact_command`** — command 표시 자체를 안 하므로 불필요.

### Notes

- **Hook 기반 turn 0회 메커니즘 한계**: Claude Code 가 hook reason 표시 시 자동 추가하는 `"⏺ UserPromptExpansion operation blocked by hook:"` prefix + `"Original prompt: ..."` suffix + 각 줄 2-space indent 는 공식 API 로 제거 불가 (docs.anthropic.com 확인). 시각적 노이즈로 수용.
- SemVer 0.x 룰: `/cn:dry-run` 제거 + slash command 처리 패러다임 전환 = breaking change → minor bump (`0.1.1` → `0.2.0`).
- pytest 베이스라인: 209 → **245 passed, 1 skipped** (cn_status 23 + box_renderer 신규 15 + on_status_command 신규 8 + on_user_prompt 7).

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

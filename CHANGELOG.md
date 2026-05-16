# Changelog

이 프로젝트의 모든 주목할 만한 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따르고, [Semantic Versioning](https://semver.org/lang/ko/) 을 준수합니다.

## [0.3.5] — 2026-05-16

**`/cn:status` 출력 재설계 + `marker.last_prompt` 필드 추가** — dogfooding 첫날 피드백 반영. 현재 세션 박스는 회고용 정보 (시작/마지막 wake/cache 추정) 제거하여 핵심 3줄로 단순화. 다른 세션 박스는 중첩 박스로 재구성하고 sid 식별을 돕는 last_prompt (첫 줄 40자) 추가.

### Added

- **`Marker.last_prompt: str`** (신규 필드) — on_user_prompt hook 이 stdin payload 의 `prompt` 필드를 첫 줄 + 40자 truncate (`…` 표시) 후 marker 에 저장. `/cn:status` 의 "다른 세션" 박스에서 세션 식별용으로 표시.
- **`tests/lib/test_marker.py`**: round-trip 에 `last_prompt` 포함 + 백워드 호환 테스트 (`test_load_legacy_marker_without_last_prompt`).
- **`tests/scripts/test_on_user_prompt.py`** `TestLastPromptCapture` 클래스 (7 신규 테스트): short/long truncate, 40자 경계, multiline 첫 줄 only, empty/missing 시 보존, control char strip.
- **`tests/scripts/test_cn_status.py`**: 다른 세션 박스 신규 형식 (last_prompt 표시 / 백워드 — / max show 5개 제한) 테스트.

### Changed

- **`scripts/cn_status.py` `_build_session_box`**: 현재 세션에서 `시작` / `마지막 wake/notify` / `cache 추정` 3개 줄 제거. `sid` / `wake/notify count` / `다음 발동 예상` 3줄만 유지.
- **`scripts/cn_status.py` `_build_other_sessions_box`**: 단일 박스 + per-line 표시 → **중첩 박스 (outer "다른 세션" + inner sid-titled 박스)**. 본문 = `다음 fire 시간` + `마지막 프롬프트`. `latest_fire` 내림차순 정렬, 최대 5개 표시 (초과 시 `... 외 N개`).
- **`scripts/cn_status.py` `_build_settings_box`**: `cache-necromancer v0.3.0` hard-code → `.claude-plugin/plugin.json` 에서 dynamic 읽음 (`_plugin_version()` helper).
- **`scripts/on_user_prompt.py`**: stdin payload 의 `prompt` 필드 추출 + `_truncate_prompt()` (첫 줄 + 40자 + `…` + control char strip) → `marker.last_prompt` 저장 추가. wake_count reset 로직은 그대로.
- **`lib/marker.py` `Marker` dataclass**: `last_prompt: str = ""` 필드 추가. `save()` JSON body 에 포함. `load()` 는 `data.get("last_prompt", "")` 로 백워드 호환.
- **`TECH_SPEC.md` §3.1 / §5 / §8**: marker schema, on_user_prompt 동작, /cn:status mockup 갱신.

### Migration

옛 marker file (v0.3.4 이전) 은 자동 호환 — `last_prompt` 필드 없으면 빈 string default, /cn:status 에서 `"—"` 로 표시됨. 새 user input 마다 자연스럽게 채워짐.

별도 cleanup 작업 불필요.

### 도구 정신 갱신 (PRD §8)

PRD §8 의 "민감정보 미기록" 원칙에 **last_prompt 예외 명시**. 근거:
- marker file 권한 0600 (다른 로컬 사용자 read 불가)
- single-user alpha 단계 가정
- 외부 marketplace 공개 시 opt-out flag 도입 검토

### Notes

- pytest baseline: 108 → **118** (+10 신규 테스트)
- net 변경: 코드 +130 / -50 정도. 테스트 +120 / -10.

## [0.3.4] — 2026-05-16

**`/cn:config` 슬래시 명령 instructions 갱신** — v0.3.0 사이클에서 빠진 정리 항목. v0.2.x 옵션을 묻고 daemon 재시작을 실행하던 outdated instructions 를 v0.3.0+ 호환 옵션으로 재작성.

### Changed

- **`commands/cn:config.md`**: 인터랙티브 질문 4개를 v0.3.0+ config 키로 재구성:
  - Q1 `mode` (notify/auto/hybrid) — "fire" → "wake" 용어 통일
  - Q2 `refresh_interval_minutes` (2/30/50/90) — default 55 → 50 반영 (1h cache 안전 마진)
  - Q3 `max_refresh_count` (5/10/20/50) — 동일
  - Q4 `system_notification` (true/false) — v0.2.x 의 `imminent_threshold_minutes` 자리 대체
- 적용 시점 안내: "데몬 재시작 필요" → "다음 Stop hook 발화부터 자동 적용 (재시작 불필요)".
- v0.2.x deprecated 키 보존 안내 + `pkill` / `daemon.lock` 명령 제거.
- 기본 템플릿 갱신: v0.3.0+ 의 [general]/[notify]/[refresh] 구조로 단순화.

### Fixed

- 사용자가 `/cn:config` 호출 시 deprecated `imminent_threshold_minutes` 가 묻혀 v0.3.0+ 환경에 무의미한 옵션이 추가되던 회귀 해소.
- 변경 후 무의미한 `pkill -f "python.*-m daemon"` 실행되던 부작용 제거 (daemon 폐기됨).

### Notes

- 코드 변경 없음. slash command instructions only.
- v0.3.0~v0.3.3 사용자는 plugin update 시 새 instructions 가 자동 적용.

## [0.3.3] — 2026-05-16

**`cn install` / `cn uninstall` CLI 폐기** — plugin marketplace 가 공식 설치 경로로 안착했고 (`/plugin install cache-necromancer` 한 명령으로 hook 자동 등록), 수동 fallback CLI 의 실 사용 빈도가 거의 0 으로 확인됨. YAGNI 적용하여 ~500줄 정리.

### Removed

- **`lib/install.py`** — `cn install` / `cn uninstall` CLI 본체 삭제 (261줄).
- **`tests/lib/test_install.py`** — 관련 테스트 25개 삭제 (238줄).
- **`pyproject.toml`**: `[project.scripts] cn = "lib.install:main"` entry 제거 — `cn` 명령어가 더 이상 설치되지 않음.

### Changed

- **`scripts/cn_status.py`**: 출력 문구의 "(cn install)" → "(수동 등록)", "또는 cn install" 제거. plugin manifest 등록 검사는 그대로.
- **`tests/scripts/test_cn_status.py`**: 변경된 출력 문구에 맞춰 assertion 갱신.
- **`README.md`**: "Plugin marketplace 미사용 환경 (fallback)" 섹션 삭제. plugin 설치만 공식 경로.
- **`TECH_SPEC.md` §7**: `lib/install.py` 명세 삭제.

### Migration

기존 `cn install` 로 settings.json 에 hook 등록한 사용자:

```bash
# 1. ~/.claude/settings.json 의 hooks.Stop 항목에서
#    cache-necromancer/scripts/refresh.py 포함된 entry 수동 삭제

# 2. plugin marketplace 로 재설치 (자동 등록)
/plugin install cache-necromancer
```

`cn` 명령어 자체는 v0.3.3 이후 사라짐. shell 의 `cn: command not found` 발생 시 본 폐기가 원인.

### Notes

- net 코드 변경: -490 줄 / +N 줄 (대부분 삭제)
- pytest baseline: 124 → 99 (test_install.py 25개 삭제)
- v0.4.0 에서 plugin marketplace 가 막힌 환경 (회사 보안 등) 의 fallback 이 진짜 요청되면 재도입 검토.

## [0.3.2] — 2026-05-16

**로그 파일명 정리** — v0.2.x daemon 폐기 후에도 남아있던 `daemon.log` 파일명을 `cn.log` 로 rename. 함께 dead code (`log_fire` / `log_user_turn` + `fire.log` / `user_turn.log`) 제거 (YAGNI — v0.4.0 metrics 트랙에서 재설계 예정).

### Changed

- **`lib/logger.py`**: `_append("daemon.log", ...)` → `_append("cn.log", ...)` (`log_info` / `log_warn` 둘 다). docstring 갱신.
- **`tests/lib/test_logger.py`**: 활성 테스트 (log_info/log_warn/append/silent/permissions) 의 `daemon.log` → `cn.log` path 갱신.

### Removed

- `lib/logger.py`: `log_fire()` 함수 + `fire.log` 파일 (v0.3.0 fire 개념 폐기 후 dead).
- `lib/logger.py`: `log_user_turn()` 함수 + `user_turn.log` 파일 (Phase 4 대시보드용으로 도입됐으나 v0.3.0 에서 미사용 dead).
- `tests/lib/test_logger.py`: log_fire/log_user_turn 관련 테스트 5개 (`test_log_fire_writes_to_fire_log`, `test_log_fire_no_sensitive_data`, `test_log_user_turn_writes_to_user_turn_log`, `test_log_user_turn_after_fire_false`, `test_log_user_turn_no_sensitive_data`).

### Migration

옛 `~/.cache-necromancer/daemon.log.*` 파일은 자동 정리 X. 필요 시 수동 삭제:

```bash
rm ~/.cache-necromancer/daemon.log.* ~/.cache-necromancer/fire.log.* ~/.cache-necromancer/user_turn.log.*
```

### Notes

- v0.3.1 은 docs/spec sync + 폴더 reorg PR (PR #13). version bump 없이 docs only.
- net 코드 변경: -111 줄 / +14 줄 (logger.py + test_logger.py)
- pytest baseline 영향: -5 테스트 (dead 테스트 삭제)

## [0.3.0] — 2026-05-16

**Architecture 전면 전환** — v0.2.x daemon + `claude -p` fire architecture 가 cache namespace 분리 (chat 의 system prompt 와 `-p` 의 system prompt 가 byte 단위로 다름) 때문에 실제로는 cache TTL 갱신 못 하던 fundamental 결함을 발견. Claude Code 의 native **Stop hook + asyncRewake** 로 chat 세션이 자기 자신을 wake 하는 방식으로 전환 (system prompt + tools byte-exact 보존 → cache prefix 100% hit).

검증 결과 (POC):
- 30분 sleep 후 wake → cr=44.55K (cache 100% hit, $0.044)
- 1M context 두 번째 wake → cc=586 / cr=153.7K / $0.085 (94% 절감)

### Breaking Changes

- **Daemon 메커니즘 폐기**: `daemon/` 디렉토리 전체 (11 파일), `lib/lockfile.py`, `lib/state.py`, `lib/plugin_state.py` 삭제. `~/.cache-necromancer/lock` + `state/` 디렉토리 사용 안 함.
- **Config 옵션 폐기** (detect 시 stderr 경고 + 무시):
  - `notify.terminal_bell`, `notify.imminent_threshold_minutes`
  - `refresh.prompt`, `refresh.fire_timeout_seconds`
  - `[advanced]` 전체 (12 필드 — daemon poll, fire watchdog, backoff 등)
- **`/cn:dry-run` 명령 폐기**: subprocess fire preview 의미 사라짐.
- **`refresh_interval_minutes` default 변경**: 55 → 50 (1h cache 기준 + 안전 마진). 기존 명시값은 유지.
- **`/cn:status` 출력 재설계**: 데몬 박스 제거, 세션은 marker 기반.

### Added

- **`scripts/refresh.py`** (신규) — Stop hook 의 asyncRewake 본체. mode 별 sleep + wake/notify 분기.
- **`lib/marker.py`** (신규) — per-session marker file. atomic write (`tempfile + os.replace + 디렉터리 fsync`). `cleanup_stale(7일)` helper.
- **`lib/install.py`** (신규) + `cn install` / `cn uninstall` CLI — plugin marketplace 미사용 환경 fallback. settings.json 에 Stop hook 추가/제거. v0.2.x stale daemon detect 후 사용자 안내.
- **`lib/notify.py`** (신규) — macOS osascript 알림 wrapper.
- **`lib/config.py`**: `detect_deprecated_keys()`, `parse_config_file()` public API 추가.
- **Hook config**: `hooks/hooks.json` 의 Stop hook 이 `refresh.py` + `asyncRewake: true` + `timeout: 3600` (default 10분 timeout 회피).
- **`pyproject.toml`**: `[project.scripts] cn = "lib.install:main"` 추가, version 0.3.0.
- **테스트**: marker / refresh / install / cn_status / on_user_prompt / on_session_end 신규 (~70 테스트).

### Changed

- **`scripts/on_user_prompt.py`**: state 추적 폐기 → marker.wake_count = 0 reset 만.
- **`scripts/on_session_end.py`**: 현재 sid marker 삭제 + 7일 stale glob 정리.
- **`scripts/cn_status.py`**: 마커 기반 출력 + plugin/hook 등록 상태 + deprecated config 경고.
- **`lib/mode_help.py`**: "fire" → "wake" 표현 통일, "데몬 재시작" → "새 chat 세션".
- **`.claude-plugin/plugin.json`**: version 0.3.0, description "via Stop hook + asyncRewake".

### Removed

- `daemon/` 11 파일 (`__main__`, `clock`, `handler`, `notifier`, `poller`, `refresh`, `scheduler`, `spawn`, `transcript`, `watchdog`).
- `lib/lockfile.py`, `lib/state.py`, `lib/plugin_state.py`.
- `scripts/on_stop.py` (refresh.py 로 대체).
- `tests/daemon/` 11 + `tests/lib/test_lockfile.py` + `test_state.py` + `tests/scripts/test_on_stop.py`.
- `commands/cn:dry-run.md` (이미 v0.2.0 에서 삭제).

### Fixed (post-PR)

- **`config.toml` 자동 생성 누락 fix** (cf9e37c) — v0.2.x 에서는 daemon spawn 시 `ensure_config_file()` 호출했으나 v0.3.0 daemon 폐기로 호출 위치가 사라져 첫 hook fire 시 config 없으면 silent 종료하는 회귀가 있었음. `scripts/refresh.py` 진입부 + `lib/install.py install_main` 양쪽에서 호출하도록 복구. PRD §3.2 약속 충족.
- **`refresh.py` stdin session_id 처리 fix** (521a66e, P0) — Claude Code hook 은 stdin JSON 으로 `{"session_id": ...}` 전달. v0.3.0 초기 구현은 `os.environ["CLAUDE_CODE_SESSION_ID"]` 만 사용 → 사용자 환경에서 wake 가 영영 발생 안 함. `_resolve_session_id()` 추가: stdin 우선 + env fallback. `on_user_prompt.py` / `on_session_end.py` 와 패턴 일관.

### Migration

```bash
# 1. v0.2.x daemon 정지
pkill -f "python.*-m daemon" || true

# 2. stale 파일 정리
rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state

# 3. 업그레이드
/plugin update cache-necromancer

# 4. 새 chat 세션 시작 (settings hot-reload 안 됨)
```

기존 `config.toml` 의 호환 옵션 (mode / refresh_interval_minutes / max_refresh_count / system_notification / hybrid_wait_seconds) 은 그대로 동작. 폐기 옵션은 무시 (stderr 경고).

### Notes

- net 코드 변경: -5478줄 / +1900줄 (daemon 폐기 + 신규 marker/refresh/install/cn_status)
- pytest: 251 → **124+ 통과** (daemon 관련 폐기 후 base 작아짐)
- 진단 + POC 비용 ~$5 (1M context 환경)

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

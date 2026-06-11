# Changelog

이 프로젝트의 모든 주목할 만한 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따르고, [Semantic Versioning](https://semver.org/lang/ko/) 을 준수합니다.

## [0.5.2] — 2026-06-11

### Fixed

- **self-gate 오발동 — 다운로드만 된 새 버전이 활성 버전의 hook 을 침묵시키던 버그**
  (`lib/install_version.py`): `is_latest_install()` 판정 기준을 "install cache 내
  최대 버전 디렉터리"에서 **`installed_plugins.json` 의 활성 `installPath`** 로 변경.
  기존 기준에서는 `/reload-plugins` 가 새 버전을 cache 에 다운로드만 해놓으면
  (활성 pointer 는 그대로) 활성 버전의 모든 hook 이 스스로 침묵해 recap·알림이
  실종됐다 (v0.5.0 활성 + v0.5.1 다운로드 상태에서 실제 발생). json 을 못 읽거나
  이 plugin 의 entry 가 없으면 기존 최대 버전 비교로 fallback.

## [0.5.1] — 2026-06-10

### Fixed

- **macOS 알림 (N/M) 분모 수정** (`scripts/refresh.py`): manual 모드의 wake 예고 알림이
  `(wake_count+1/max_refresh_count)` 로 표시되던 것을 ping 과 동일하게
  `(소비될 회차/set 충전량)` 으로 수정 — 예: `set 2` 면 `(1/2)`, `(2/2)`.
  manual 미충전 알림(만료 임박)은 set 이 없으므로 분수 자체를 생략.
- **CHANGELOG 0.5.0 항목의 사실 오류 정정** (실제 구현과 다른 파일/필드명 서술).

## [0.5.0] — 2026-06-10

**알림 기본 + `/cn:set` 소생 — 토큰 지출 경로 명시화**

제품 방향 전환: "캐시가 죽기 전에 알려준다. 살리는 건 사용자가 `set` 했을 때만."

### Added

- **`/cn:set N` 슬래시 명령** (`scripts/cn_set.py`, `commands/cn:set.md`, `scripts/on_status_command.py` 라우팅 — LLM turn 0회): 현재 세션에 wake 예산 충전 (N회 소생, `min(N, max_refresh_count)` 상한). `/cn:set 0` = 취소, `/cn:set` (무인자) = 현재 상태 표시. `arm=always` 중 호출 시 안내 메시지. 예산은 복귀(충전 후 **wake 가 1회 이상 일어난 뒤** 들어온 실제 입력) 시 자동 소멸 — set 직후 추가 프롬프트는 예산 유지.
- **`lib/marker.py`**: wake 예산 필드 추가 (`set_budget_remaining`, `set_budget_total`, `set_charged_at_ns`).
- **cn: 메타 명령 activity 제외** (`scripts/on_user_prompt.py`): `/cn:set`·`/cn:status`·`/cn:config` 는 user activity 로 취급하지 않음 — set 직후 pending timer 가 supersede 되지 않도록 보장.
- **recap 2번째 줄**: 예산 충전 시 남은 wake 횟수 / 생존 시한 표시 (4개 언어).
- **`/cn:status` 예산 표시**: arm 정책 + 남은 예산 + 생존 시한.

### Changed

- **config 구조 개편** (`lib/config.py`): `mode` enum (notify/auto/hybrid) 폐기 → 2축:
  - `[notify] enabled` — 만료 임박 알림 on/off (구 `system_notification`)
  - `[wake] arm` (`"manual"` 기본 / `"always"`) + `grace_seconds` (구 `hybrid_wait_seconds`)
  - `manual` = `/cn:set` 충전 시에만 wake, `always` = 매 turn 자동 arm (기존 hybrid/auto 동작 opt-in 유지).
- **기본값 변경**: 신규 설치 `arm = "manual"` — 알림만, 자동 wake 없음 (기존 사용자는 legacy 매핑으로 기존 동작 유지).
- **`plugin.json` `userConfig.mode` 제거**: config.toml + `/cn:config` 단일 설정 창구로 일원화.
- **`config.toml.example`** / **`commands/cn:config.md`**: v0.5.0 템플릿 + 신 키 기준 Q&A.
- **`hooks/hooks.json` description**: v0.5.0 반영.
- **임시 호환 property 제거** (`Config.mode`, `Config.refresh`, `NotifyConfig.system_notification`).

### Migration

v0.4.x 이하 legacy 키 자동 매핑 (로드 시 신 키 우선):

| 구 키 | 신 해석 |
|---|---|
| `mode = "hybrid"` | `arm="always"` + `notify.enabled=true` |
| `mode = "auto"` | `arm="always"` + `notify.enabled=false` |
| `mode = "notify"` | `arm="manual"` + `notify.enabled=true` |
| `[notify] system_notification` | `notify.enabled` |
| `[refresh] hybrid_wait_seconds` | `wake.grace_seconds` |

기존 hybrid/auto 사용자는 자동 매핑으로 동작 유지 — 신규 설치만 `manual` 기본.

### Tests

302 pytest 통과.

---

## [0.4.2] — 2026-05-26

**옛날 버전 refresh.py sleep 잔존 process 자동 정리**

### Fixed

- **옛날 버전 refresh.py SIGTERM** (`scripts/refresh.py`): 0.4.1 의 self-gate 가 새 fire 의 옛날 버전 호출은 차단하지만, plugin update **직전**에 spawn 되어 이미 sleep 중인 옛날 refresh.py 프로세스는 영향을 못 받았다 (대표 사례: `time.sleep(50*60)` 중인 25개의 0.4.0 refresh.py 가 0.4.1 install 후에도 깨어나 옛날 포맷 알림 발사). 진입부의 `is_latest_install()` 통과 직후 `_kill_older_buddies()` 가 `pgrep -laf` 로 자기보다 옛날 버전의 cache-necromancer refresh.py 를 찾아 `SIGTERM`. pgrep 미설치 / SIGTERM 실패 / version 파싱 실패 모두 silent. dev 환경 (parents[1] 이 version 패턴 아닐 때) 은 자동 skip.

### Tests

7 added → 전체 235 pytest 통과.
- `test_refresh.py::TestKillOlderBuddies`: 옛날 kill / 같은·새 버전 skip / 자기 PID skip / subprocess error silent / pgrep missing silent / os.kill 실패 silent / dev 환경 skip

## [0.4.1] — 2026-05-26

**옛날 install 버전 self-gate — 업데이트 시 중복 fire 차단**

### Fixed

- **옛날 버전 hook fire 차단** (`lib/install_version.py` 신규, 5개 hook entry point): Claude Code plugin 시스템은 hook command 경로를 register 시점의 절대경로로 박기 때문에 marketplace 가 새 버전으로 bump 되어도 옛날 세션의 register 는 그대로 살아있다. `/reload-plugins` 가 새 register 를 추가만 하고 옛날 register 를 제거하지 않아 같은 세션이 0.3.13 + 0.4.0 처럼 두 버전을 동시 fire 시키는 현상이 관찰됐다. 각 hook entry point (`refresh.py`, `on_user_prompt.py`, `on_session_end.py`, `on_recap.py`, `on_status_command.py`) 진입부에서 `is_latest_install()` 로 자기가 install cache 의 latest 버전인지 확인 → 아니면 즉시 exit. dev source / 비-install 환경은 자동 통과. 효과는 0.4.1 부터 적용 — 0.4.1 코드가 install 된 이후의 옛날 버전 fire 만 차단.

### Tests

6 added → 전체 228 pytest 통과.
- `test_install_version.py`: latest match / older mismatch / dev 환경 / 단일 install / SemVer tuple 비교 / 비-version sibling 무시

## [0.4.0] — 2026-05-26

**활성 chat 세션 wake 가드 + 알림 식별 메타데이터**

### Added

- **`Marker.last_user_activity_at_ns` 필드**: `lib/marker.py` — 진짜 user input 시각 (ns) 기록. legacy marker 백워드 호환 (필드 없으면 0 default).
- **알림 식별 메타데이터** (`lib/notify.py`, `scripts/refresh.py`): macOS 알림에 세션 식별 정보 노출 — 여러 세션 동시 사용 시 어느 프로젝트의 알림인지 즉시 구분 가능.
  - title: `cache-necromancer · <project basename>`
  - subtitle: `<sid8> · (N/M)`
  - body: `<단축 경로> — <기존 메시지>`

### Fixed

- **활성 chat 세션 wake 가드** (`scripts/refresh.py`, `scripts/on_user_prompt.py`): 이전 버전은 supersede 기준이 `latest_fire` (Stop hook fire = model 응답 종료 시점) 만이라, model 응답이 50분 넘게 진행되는 동안 사용자가 활발히 prompt 를 치고 있어도 wake/notify 가 발생하는 hole 이 있었음. UserPromptSubmit hook 이 진짜 user input 일 때 `last_user_activity_at_ns` 를 갱신하고, refresh.py 의 supersede 체크 (첫 sleep 후 + hybrid_wait 후 두 곳) 가 `latest_fire > my_ts OR last_user_activity_at_ns > my_ts` 로 묶임. `cn_status` 의 "next fire" 계산은 `latest_fire` 기준 유지 (의미 분리).

### Changed

- **`lib/notify.py`**: `notify()` 에 `subtitle` 인자 추가, osascript 이스케이프를 `_osa_escape` 헬퍼로 분리 (`\` → `\\` 먼저, `"` → `\"` 다음).
- **`pyproject.toml`**: 0.3.13 → 0.4.0 (이전 릴리즈에서 누락된 sync).

### Tests

5 added → 전체 222 pytest 통과.
- `test_marker.py`: round-trip 에 새 필드, legacy 마커 backward-compat 추가
- `test_on_user_prompt.py`: `TestUserActivityTimestamp` — user input 시 갱신 + system event (PING/task-notification) 갱신 X
- `test_refresh.py`: `TestNotifyMetadata` (title/subtitle/body 검증 3개), user activity supersede (auto/hybrid 2개)

## [0.3.14] — 2026-05-26

**SessionEnd 후 좀비 wake 버그 픽스**

### Fixed

- **좀비 wake/notify 차단**: `scripts/refresh.py` — Stop hook 의 백그라운드 refresh.py 가 sleep 중일 때 SessionEnd 가 marker 파일을 삭제해도, sleep 후 `Marker.load()` 가 fresh marker (`latest_fire=0`) 를 반환해 supersede 검사 (`latest_fire > my_ts`) 를 통과하던 문제. 종료된 세션이 알림을 발사하고 `latest_fire=0` 좀비 marker 가 디스크에 재생성됨. sleep 후 load 두 군데 (첫 sleep / hybrid_wait) 에 `latest_fire == 0` 가드 추가.

### Tests

회귀 가드 2개 추가 (`test_session_end_during_sleep_skips_and_no_zombie`, `test_session_end_during_hybrid_wait_cancels_wake`) → 전체 214개 pytest 통과 유지.

## [0.3.13] — 2026-05-24

**`/cn:status` 박스 재구성 + 4 언어 i18n + 폴더 위치 + stale 세션 필터**

### Added

- **marker schema `cwd` 필드**: `lib/marker.py` — UserPromptSubmit hook 의 stdin `cwd` 를 저장. `/cn:status` 의 "다른 세션" 박스에서 home 약식 (`~/path`) 표시.
- **`lib/i18n.py` 확장**: `STATUS_LABELS` (4 언어 × 박스 라벨) + `status_label()` + `mode_label_i18n()` 추가. recap 메시지에 이어 `/cn:status` 도 `[general].language` 따라 ko/en/ja/zh 출력.
- **stale 세션 필터**: 다음 발동 예상이 과거 (음수 delta) 인 marker 는 "다른 세션" 표시에서 제외. wake cycle 종료된 세션 (max_refresh_count 도달 / chat 종료) 의 노이즈 차단. cleanup_stale 7d 와 별개 — marker 파일 자체는 유지.

### Changed

- **`/cn:status` 박스 재구성** (v0.3.13 mockup):
  - 상단 `mode: ... · refresh_interval ...` 헤더 줄 제거 → 하단 "상태" 박스로 이동
  - "다른 세션": 라벨 통일 + `폴더:` 추가 (next_fire / prompt / cwd 3줄)
  - "설정 상태" → "상태" 로 rename. `hook 등록` / `deprecated config` 노출 제거 (alpha 단계 noise 차단)
- **`scripts/on_user_prompt.py`**: stdin `cwd` 캡처 → `marker.cwd` 갱신 (빈 문자열은 기존 값 보존).

### Tests

103 added/updated → 전체 pytest 통과 유지.

## [0.3.12] — 2026-05-23

**Recap systemMessage + 4 언어 i18n + KST 제거 + `cache_ttl_minutes` 분리** — turn 종료 즉시 cache 만료 시각을 Claude Code recap 영역에 표시.

### Added

- **`scripts/on_recap.py`**: Stop hook sync 본체. turn 종료 즉시 `🪦 캐시는 H시 M분에 죽어요.` systemMessage 출력 (wake 트리거 X, 정보성).
- **`lib/i18n.py`**: 언어별 메시지 + 시각 표기 (`ko`/`en`/`ja`/`zh`).
  - ko: `🪦 캐시는 9시 37분에 죽어요.`
  - en: `🪦 Cache dies at 09:37.`
  - ja: `🪦 キャッシュは9時37分に死にます。`
  - zh: `🪦 缓存将在9点37分死亡。`
- **`config.toml`** 신규 필드:
  - `[general].cache_ttl_minutes = 60` — Anthropic 1h ext cache TTL (recap 메시지 시각 = `fire + ttl`).
  - `[general].language = "en"` — 메시지 언어 (default "en", invalid 값 → stderr warn + "en" fallback).
- **`hooks/hooks.json`**: Stop 배열에 sync `on_recap.py` (timeout 5) 추가, async `refresh.py` 그대로.

### Changed

- **`scripts/refresh.py`**: PING fire 시각 KST hardcode 제거 → 사용자 시스템 local time 사용. PING 형식 `[cn:keepalive HH:MM, N/M]` (KST suffix 제거), reply 형식 `ok @HH:MM (N/M)` 유지.
- **`README.md`**: banner 이미지 추가, recap 메시지 섹션 신설, config 예제 갱신.

### Fixed

- **recap 메시지 시각 계산**: `refresh_interval_minutes` (wake 주기, default 50) 와 `cache_ttl_minutes` (cache 만료, default 60) 분리. 기존엔 메시지가 `fire + 50` 으로 계산되어 실제 cache 만료보다 10분 일찍 표시 (`🪦 죽어요` 의미 불일치).

### Tests

- 신규: `tests/lib/test_i18n.py` (22건), `tests/scripts/test_on_recap.py` (16건 — 4 언어 메시지 + 자정 넘김 + ttl 가드 + interval/ttl 분리 + default fallback).
- 갱신: `tests/scripts/test_refresh.py` (KST 제거 검증 + freezegun PING 회귀 가드).
- 175 → **179 passed**.

### Notes

- **silent fail (PRD 불변)**: 모든 예외 top-level catch → exit 0. chat 동작 차단 X.
- **`refresh_interval_minutes` vs `cache_ttl_minutes`**: 전자는 wake 주기 (TTL 보다 안전 마진 만큼 짧음), 후자는 메시지 시각 계산용. 사용자가 5분 cache 모드면 `cache_ttl_minutes = 5` 로 변경 가능.

## [0.3.11] — 2026-05-19

**`on_user_prompt` 자기간섭 fix — `wake_count` 가 매 wake 마다 `0` 으로 reset 되어 PING 표시가 `1/N` 무한 반복 + `max_refresh_count` cap 무력화되던 버그 수정.**

### Fixed

- **`scripts/on_user_prompt.py`**: stdin `prompt` 가 `<task-notification>` 으로 시작하거나 `[cn:keepalive` 를 substring 으로 포함하면 `wake_count` reset / `last_prompt` 갱신 skip.
  - **원인**: v0.3.10 의 PING (`[cn:keepalive ... N/M]`) 이 raw 가 아니라 Claude Code 가 `<task-notification>...<system-reminder>...PING...</system-reminder>` wrapper 안에 감싸서 UserPromptSubmit hook 의 `stdin.prompt` 로 전달. 기존 코드의 `startswith(PING_PREFIX)` 가 매칭 실패 → reset 진행 → 매 wake 마다 `wake_count=0` → `1/N` 반복 + cap 미발동.
  - **추가 발견**: Claude Code 의 background `<task-notification>` (e.g. `Bash run_in_background` 완료 알림) 도 UserPromptSubmit hook trigger. 이것도 사용자 input 아니므로 skip.
  - **결과**: `1/10 → 2/10 → 3/10 → ... → 10/10` 정상 누적, `max_refresh_count` cap 의도대로 작동 (10 회 도달 후 wake skip → cost 상한 보장).

### Tests

- `tests/scripts/test_on_user_prompt.py::TestPingSelfInterference` 4건:
  - raw PING / **wrapped PING (실제 형식)** / marker 없을 시 부수효과 X / regression
- `tests/scripts/test_on_user_prompt.py::TestSystemEventSkip` 2건:
  - plain `<task-notification>` (PING 없음) skip / `<` 로 시작하는 user input (`<div> 태그 어떻게 써?`) 은 reset 정상
- `tests/scripts/test_on_user_prompt.py::TestPolicyEdgeCases` 4건 (codex 권장 정책 고정):
  - 사용자 텍스트 안에 `[cn:keepalive` 포함 시 skip (false positive 수용 정책 명시)
  - partial prefix `[cn:keepaliv` 는 reset 정상 (경계)
  - leading whitespace + `<task-notification>` 는 reset (startswith 정책)
  - `<system-reminder>` 단독 wrapper + PING 도 substring 으로 skip
- 131/131 pass.

### Notes

- **substring 매칭 false positive**: 사용자가 일부러 메시지에 `[cn:keepalive` 텍스트를 포함시키면 reset skip. 영향 범위 = 자기 marker 의 wake_count 만, `max_refresh_count` cap 으로 보호. single-user alpha 가정상 수용.
- `PING_PREFIX` 상수는 `scripts/refresh.py` 와 `scripts/on_user_prompt.py` 양쪽에 하드코딩 (현재 `scripts/` 가 패키지 아님). 추후 `lib/` 로 통합 예정.
- 진단 과정에서 디버그 로그 추가 → 실제 stdin payload 형식 확인 → wrapped PING 발견 → fix 보완 (`startswith` → `in` substring + `<task-notification>` 시작 체크).

## [0.3.10] — 2026-05-17

**Wake PING 에 fire 시각 + repeat count 표시** — chat history 만 봐도 언제 몇 번째 wake 였는지 확인 가능. `ok` 한 마디뿐이라 어색하던 wake-up turn 의 가독성 개선.

### Changed

- **`scripts/refresh.py`**:
  - `PING_MESSAGE` 정적 상수 → `PING_PREFIX` + `_build_ping(wake_count, max_count)` 동적 빌더로 교체.
  - 메시지에 KST `HH:MM` + `N/M` (`wake_count/max_refresh_count`) 포함.
  - 응답 형식을 `ok @HH:MM (N/M)` 으로 강제 — chat scrollback 에서 시점/잔여 횟수 즉시 식별.
  - `_do_wake` 시그니처에 `config` 인자 추가 (`max_refresh_count` 참조).
  - Before: `[cn:keepalive] reply 'ok' only. ...`
  - After: `[cn:keepalive 16:42 KST, 7/10] reply with exactly 'ok @16:42 (7/10)'. ...`
- **`tests/scripts/test_refresh.py`**: `PING_MESSAGE` import → `PING_PREFIX` 로 교체, 시각/카운트 포맷 검증 테스트 추가.

### Notes

- KST 변환은 `datetime.now(timezone(timedelta(hours=9)))` 로 system timezone 무관.
- output token: `ok` (1 token) → `ok @16:42 (7/10)` (~10 token). cache hit (input prompt) 에는 영향 X.
- max wake 도달 시 wake 자체가 skip 되므로 메시지 표시 안 됨 (변동 없음).

## [0.3.9] — 2026-05-16

**Wake `PING_MESSAGE` 에 minimal output 지시 추가** — 모델이 wake-up turn 에서 'ok' 외 추가 토큰 발생 가능성 차단 강화.

### Changed

- **`scripts/refresh.py:33`** `PING_MESSAGE`:
  - Before: `[cn:keepalive] reply 'ok' only. No tools, no analysis.`
  - After: `[cn:keepalive] reply 'ok' only. No tools, no analysis. Use minimal output tokens.`

### Notes

- pytest 영향 X — test 는 `PING_MESSAGE` 상수 import 후 매칭이라 자동 sync.
- 코드 변경: 1줄. wake 비용 안정성 ↑.

## [0.3.8] — 2026-05-16

**docs sync** — v0.3.5~v0.3.7 사이클에서 누락됐던 README + TECH_SPEC §8 mockup 갱신. 코드 변경 0줄, docs only.

### Changed

- **`README.md`**:
  - "빠른 시작" 의 `/cn:status` 설명: "wake/notify count + cache 추정 만료" → "다음 발동 예상"
  - `/cn:status` mockup 을 v0.3.7 형식으로 통째 갱신 (헤더 2줄 / 시작·마지막 wake·cache 추정 제거 / `repeat count` / 다른 세션 중첩 박스 / dynamic version)
  - 트러블슈팅 "wake 가 발생하지 않음" 의 `wake/notify count` → `repeat count`
- **`TECH_SPEC.md` §8**: mockup 을 v0.3.7 형식으로 갱신 + v0.3.6 (빈 marker filter) / v0.3.7 (헤더 줄바꿈 + repeat count) 변경 노트 추가

### Notes

- 본 commit 은 docs only 변경이라 사용자 명시 승인으로 **main branch 직접 commit** (PR 우회). 글로벌 룰 (development.md: "main 직접 작업 절대 금지") 의 1회성 예외 — 본 commit 한정.
- pytest 영향 없음 (코드 미변경).

## [0.3.7] — 2026-05-16

**`/cn:status` 헤더 줄바꿈 + `wake/notify count` → `repeat count` rename** — v0.3.6 dogfooding 직후 가독성 피드백 반영.

### Changed

- **`scripts/cn_status.py` `_build_header_line` → `_build_header_lines`**: 단일 long line → 2줄 분리.
  - 줄 1: `mode: <label> — <설명>`
  - 줄 2: `refresh_interval: 50m · max_refresh: 10`
- **`scripts/cn_status.py` `_build_session_box`**: 현재 세션의 `wake/notify count` 라벨 → **`repeat count`** (짧고 명확). 다른 라벨도 padding 재정렬.

### Notes

- pytest baseline: 120/120 유지 (label 변경 1건 test assertion update)
- 코드 변경: +6 / -5 (label/format only)
- `wake_count` 데이터 필드명은 그대로 (TECH_SPEC §3.1 — mode 무관 통합 카운터)

## [0.3.6] — 2026-05-16

**`/cn:status` 의 "다른 세션" 박스에서 빈 marker 필터** — v0.3.5 dogfooding 직후 발견. `latest_fire == 0` 인 marker (on_user_prompt hook 만 발화 + Stop hook 발화 전 chat 종료된 케이스) 가 "다음: —, 마지막: —" 인 빈 박스로 노출되던 noise 해소.

### Fixed

- **`scripts/cn_status.py` `_build_other_sessions_box`**: `latest_fire > 0` 인 marker 만 표시하도록 filter 추가. 모든 다른 세션이 빈 marker 면 `없음` 표시.

### Added

- **`tests/scripts/test_cn_status.py`**: 2개 신규 (`test_other_session_filters_empty_markers`, `test_other_session_all_empty_shows_none`).

### Notes

- pytest baseline: 118 → **120** (+2)
- 코드 변경: +6줄 (filter 한 줄 + docstring)

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

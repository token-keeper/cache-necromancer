# cache-necromancer v0.5.0 — set 소생 모드 Design

> **제품 방향 전환: "캐시가 죽기 전에 알려준다. 살리는 건 사용자가 `set` 했을 때만."**
> 자동 wake 는 명시적 `/cn:set N` 요청이 있을 때만 발생. 토큰 지출 경로가 set 하나로
> 수렴되어 비용이 100% 예측 가능해진다. 기존 상시 자동 갱신은 `arm = "always"`
> config opt-in 으로 격하.
>
> 기획 픽스: 2026-06-10 grill-me 세션 (Notion: "cache-necromancer set 모드" 페이지)

## 1. 배경 / 목적

- 현재(≤0.4.x): 매 turn Stop hook 이 무조건 fire → wake 가 일어나면 wake turn 이
  다시 fire → `max_refresh_count`(10) 까지 연쇄. 퇴근 후 안 돌아와도 최대 10회 ×
  ~$0.10 이 무의식적으로 지출됨.
- 개선: 기본 동작은 **만료 임박 알림만** (토큰 0). 사용자가 자리를 비울 때
  `/cn:set N` 으로 "wake N회" 예산을 명시적으로 충전 → 그만큼만 소생하고 끝.
- "깜빡해도 살려줌" 이 필요한 사용자를 위해 `arm = "always"` 를 escape hatch 로 유지
  (founding use case 보존 — set 을 깜빡한 점심 1회의 hit→miss ×20 비용이
  always 모드 최악 낭비 $1 보다 클 수 있음).

## 2. 범위

### 포함
- config 개편: `mode` enum (notify/auto/hybrid) 폐기 → 알림/wake 2축 + `arm` 정책
- `/cn:set` 슬래시 명령 신설 (UserPromptExpansion, LLM turn 0회)
- refresh.py 의 arm/예산 분기
- 복귀 판정에 의한 예산 자동 소멸 (marker 필드 2개 추가)
- recap 2줄째 (예산 충전 상태) + i18n 4개 언어
- `/cn:status` 에 arm 정책 / 남은 예산 표시
- 구 config 키 동작 보존 마이그레이션 + deprecated 경고
- README / CHANGELOG / config.toml.example 방향 재서술

### 제외 (YAGNI)
- `/cn:set N all` (전 세션 일괄 충전) — 필요해지면 후속 버전
- `/cn:fire_reset` — 도입 안 함 (Q12: arm 변경은 `/cn:config` 로 일원화)
- macOS 알림의 액션 버튼 (알림에서 바로 set)
- set 프리셋 (set1=점심 1h 같은 이름 붙은 프리셋)
- 시스템 locale 자동 감지, recap 형식 커스터마이즈
- "Stop 표시 크게 보기 모드" / "☠️ 스타일" — 별도 버전에서 (Notion 별건)
- token-tracker 연동 (wake turn 출력 숨김) — token-tracker repo 의 별도 작업

## 3. config 구조

### 3.1 신규 구조 (v0.5.0)

```toml
[notify]
enabled = true          # 만료 임박 알림 (구 [notify] system_notification)

[wake]
arm = "manual"          # "manual"(기본): /cn:set 시에만 소생 / "always": 매 turn 자동 arm
grace_seconds = 60      # 알림 enabled 시 알림 → wake 사이 대기 (구 hybrid_wait_seconds)

[general]               # 기존 유지
refresh_interval_minutes = 50
cache_ttl_minutes = 60
max_refresh_count = 10  # wake 상한 단일 노브 (§3.3)
language = "en"
```

### 3.2 구 mode → 신 구조 의미 대응

| notify.enabled | wake 동작 | = 구 mode |
|---|---|---|
| true | off | `notify` |
| false | on | `auto` (즉시 wake) |
| true | on | `hybrid` (알림 → grace_seconds 대기 → wake) |
| false | off | (신규) recap 만 표시, 완전 무동작 |

wake 의 on/off 는 enum 이 아니라 **arm 정책 × 예산**으로 결정된다:
`always` 면 항상 on, `manual` 이면 예산 > 0 일 때만 on.

### 3.3 max_refresh_count = wake 상한 단일 노브 (Q13)

- `arm = "always"`: 기존 의미 그대로 — 한 번 자리비움당 연쇄 wake 상한
  (진짜 user prompt 시 wake_count 0 리셋, 기존 로직 유지).
- `arm = "manual"`: `/cn:set N` 충전 상한 — 실충전 = `min(N, max_refresh_count)`.
  상한이 걸리면 set 응답에 명시 (예: "🔥 10회 충전 (상한 max_refresh_count=10)").
  오타(`set 100` = $10) 비용 사고 방지망.

### 3.4 마이그레이션 — 동작 보존 (Q14)

구 키가 존재하면 다음과 같이 해석 (config 파일 자체는 건드리지 않고 로드 시 매핑):

| 구 키 | 신 해석 |
|---|---|
| `mode = "hybrid"` | `arm="always"` + `notify.enabled=true` |
| `mode = "auto"` | `arm="always"` + `notify.enabled=false` |
| `mode = "notify"` | `arm="manual"` + `notify.enabled=true` (신 기본과 동일) |
| `[notify] system_notification` | `notify.enabled` |
| `[refresh] hybrid_wait_seconds` | `wake.grace_seconds` |

- 신 키와 구 키가 공존하면 **신 키 우선**.
- 구 키 감지 시 `/cn:status` 에 deprecated 경고 1줄 ("구 config 키 감지 —
  /cn:config 로 재설정 권장"). v0.2.x 키 무시 경고와 같은 패턴.
- 효과: 기존 hybrid/auto 사용자는 업데이트 후에도 자동 갱신 유지 (조용한 breaking 없음).
  신규 설치만 새 철학의 기본값 (`manual`).
- **설치 시드 경로 정리 (codex 리뷰 F3)**: 현재 `plugin.json` 의 `userConfig.mode`
  (기본 `"hybrid"`) 가 `CLAUDE_PLUGIN_OPTION_MODE` 환경변수로 주입되고,
  `lib/config.py` 의 `ensure_config_file` 이 이를 **첫 config.toml 생성에 시드**한다.
  이 경로를 그대로 두면 신규 설치가 `mode=hybrid` 로 생성되고 위 매핑에 의해
  `arm="always"` 가 되어 "신규 설치 = manual 기본" 선언과 모순. 따라서:
  - `userConfig.mode` 를 폐기하고 신 키 기준 옵션으로 대체 (예: `userConfig.arm`)
    하거나 userConfig 자체를 제거.
  - `CLAUDE_PLUGIN_OPTION_MODE` 시드 로직은 **신규 config 생성 시 무시** (구
    config "파일" 의 mode 키만 §3.4 매핑 대상). 대체 옵션을 두는 경우 그 값만 시드.

## 4. `/cn:set` 명령

`on_status_command.py` 와 동일한 UserPromptExpansion 패턴 (command_name 매칭 →
subprocess → `decision: "block"` + reason 출력, LLM turn 0회). 인자는 prompt
문자열에서 파싱.

| 입력 | 동작 |
|---|---|
| `/cn:set N` (N≥1) | **현재 세션만** 예산 `min(N, max_refresh_count)` 충전. 응답: `🔥 wake 2회 충전 — 캐시는 최대 21:40까지 생존` (+상한 걸리면 안내) |
| `/cn:set 0` | 예산 취소 (0 으로) |
| `/cn:set` (무인자) | 현재 arm 정책 / 남은 예산 / 생존 시한 표시 |
| `/cn:set N` (arm=always 중) | no-op + 안내: "상시 자동 갱신 중이라 set 불필요. set 운용으로 바꾸려면 /cn:config" (Q12) |
| 비정수/음수 | 사용법 안내 |

- 최대 생존 시한 = `now + 실충전 × refresh_interval_minutes + cache_ttl_minutes`
  (마지막 wake 시각 + TTL).
- 다른 세션에는 영향 없음 (Q7). README / set 응답에 "다른 세션은 충전되지 않음" 명시.

## 5. marker 스키마 추가

| 필드 | 타입 | 의미 |
|---|---|---|
| `set_budget_remaining` | int (기본 0) | 남은 wake 예산. wake 시 −1 |
| `set_budget_total` | int (기본 0) | 직전 `/cn:set` 실충전량 — ping `(N/M)` 의 M, recap 표시용 |
| `set_charged_at_ns` | int (기본 0) | 마지막 충전 시각 (ns) — 복귀 판정 기준 (§6) |

기존 필드(`latest_fire`, `wake_count`, `last_wake_at`, `last_user_activity_at_ns`,
`last_prompt`, `cwd`)는 유지. 구버전 marker 파일에 신 필드가 없으면 기본값 0 으로
로드 (기존 Marker.load 패턴).

## 6. 복귀 판정 — 예산 자동 소멸 (Q8 + Q15)

> 규칙: **"set 충전 이후 wake 가 1회 이상 일어난 뒤" 들어온 진짜 user prompt 가
> 복귀다.** 복귀 시 예산 → 0.

- 구현: `on_user_prompt.py` 의 진짜-입력 분기(기존 ping/`<task-notification>`
  구분 로직 재활용)에서 `last_wake_at(ns 환산) > set_charged_at_ns` 이면
  `set_budget_remaining = 0`.
- set 직후 아직 wake 가 없는 상태(= 떠나기 전)에서 추가 프롬프트를 쳐도 예산 유지
  → "set 치고 아 맞다 하나만 더" 함정 없음 (Q15).
- `/cn:set` 프롬프트 자체의 UserPromptSubmit 은 충전(expansion)보다 먼저 실행되므로
  새 충전을 지울 수 없음. 직전 set 의 잔여 예산이 wake 소비 후였다면 지워지는데,
  곧바로 새로 충전되므로 의도와 일치.
- **cn: 메타 명령은 user activity 로 취급하지 않는다 (codex 리뷰 F1 가드)**:
  `/cn:set`·`/cn:status`·`/cn:config` 프롬프트는 `last_user_activity_at_ns` 갱신과
  복귀 판정에서 **제외**한다. 제외하지 않으면 — expansion 이 `decision:"block"` 으로
  끝나 새 Stop fire 가 없을 경우 — 직전 turn 의 sleeping refresh.py 가 activity
  가드에 의해 supersede 되어 **충전된 예산을 소비할 timer 가 사라진다**
  ("set 치고 떠남" 핵심 플로우 사망). 제외하면 직전 fire 가 sleep 후 marker 를
  재로드해 예산을 보고 wake 하므로 새 Stop 없이도 동작.
  - **구현 전 실측 검증 필수**: blocked UserPromptExpansion 후 Stop hook 이 실제로
    fire 되는지 확인 (fire 된다면 가드는 이중 안전망, 안 된다면 필수 가드).
  - 알려진 잔여 엣지: **세션의 첫 입력이 `/cn:set`** 인 경우 직전 fire 자체가 없어
    timer 부재 — set 응답에 "다음 turn 부터 보호 시작" 안내로 문서화 (YAGNI:
    expansion 에서 worker 직접 spawn 은 asyncRewake 불가로 채택 안 함).

## 7. refresh.py 분기 (런타임)

진입부(marker fire 갱신, 50분 sleep, supersede/SessionEnd/user-activity 가드)는
기존 유지. sleep 후 분기를 다음으로 교체:

```
wake 자격 = (arm == "always")
          or (arm == "manual" and set_budget_remaining > 0)

if not wake 자격:
    if notify.enabled: 알림 1회 ("캐시 곧 만료 — /cn:set N 으로 연장") → exit 0
    else: 완전 무동작 → exit 0
    # wake 없음 → 새 Stop fire 없음 → 자리비움당 알림 최대 1회 (Q9)

if wake 자격:
    if notify.enabled:
        알림 ("grace_seconds 후 자동 wake — 직접 input 시 취소")
        grace_seconds sleep + 재가드 (기존 hybrid 로직 재사용)
    wake 실행 (stderr ping + exit 2)
    manual 이면 set_budget_remaining -= 1
```

- always 의 `max_refresh_count` 도달 skip 은 기존 위치(진입부) 유지.
  manual 은 예산이 자체 상한이므로 이 체크와 무관.
- ping `(N/M)`: manual 에서는 `N = set_budget_total - set_budget_remaining`(소비량),
  `M = set_budget_total`. always 에서는 기존 그대로 `wake_count / max_refresh_count`.
  (예: `ok @16:42 (1/2)`)

## 8. recap 표시 (on_recap.py)

```
🪦 캐시는 19:00에 죽어요.
🔥 wake 2회 남음 — 최대 21:40까지 생존    ← set_budget_remaining > 0 일 때만
```

- 1줄째: 기존 그대로 (`now + cache_ttl_minutes`).
- 2줄째: manual + 예산 > 0 일 때만. 생존 시한 = `now + 남은예산 × refresh_interval
  + cache_ttl`. 예산 0 또는 always 면 1줄만 (현행 동일, Q10).
- systemMessage 멀티라인 (`\n` join).
- i18n: `build_recap_message` 에 2줄째 빌더 추가, ko/en/ja/zh 4종.

## 9. /cn:status 변경

- `mode` 행 → `arm` 정책 행 + 알림 on/off 행으로 교체
  (`mode_label_i18n` 대체: manual/always 2종 × 알림 상태 설명).
- 현재 세션에 `남은 예산` 행 추가 (manual 일 때): `🔥 2/3 남음 (~21:40)` / `없음`.
- deprecated 구 config 키 경고 (§3.4).
- `notify_warn` ("mode=notify — 갱신 효과 없음") → "manual + 예산 0 — 지금은
  알림만, /cn:set N 으로 소생" 안내로 대체.

## 10. 문서 / 배포

- README(ko/en): 핵심 피치 재서술 — "죽기 전에 알려주고, set 한 만큼만 살린다".
  mode 표 → 2축 표(§3.2) + `/cn:set` 사용법 + "다른 세션은 충전 안 됨" 명시.
- CHANGELOG: 방향 전환 + 마이그레이션 표 + "기존 hybrid/auto 사용자는 동작 유지" 명시.
- plugin.json `userConfig.mode` 설명 갱신 (arm/notify 기준).
- 배포: CLAUDE.md 릴리즈 규칙 준수 — marketplace submodule bump +
  사용자 머신은 `/plugin update` + Claude Code 재시작까지 해야 반영.

## 11. 검증 (verify)

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 신규 설치 기본 상태에서 50분 방치 | 알림 1회만, wake 0, 추가 fire 없음 |
| 2 | `/cn:set 2` → 방치 | +50m wake1, +100m wake2, 이후 정지 (총 2 fire). ping `(1/2)`, `(2/2)` |
| 3 | `/cn:set 2` → 즉시 프롬프트 1개 더 → 방치 | 예산 유지 (Q15), 시나리오 2 와 동일 진행 |
| 4 | set 2 → wake 1회 후 복귀(진짜 prompt) | 예산 0 소멸, recap 1줄로 복귀 |
| 5 | `/cn:set 15` | 10회 충전 + 상한 안내 |
| 6 | `arm=always` 구성 + `/cn:set 1` | no-op + /cn:config 안내 |
| 7 | 구 config (`mode=hybrid`) 로 로드 | always + 알림 on 으로 동작, /cn:status 에 deprecated 경고 |
| 8 | recap | 예산 >0: 2줄 / 예산 0: 1줄 / ko·en·ja·zh 각 렌더 |
| 9 | 다중 세션에서 한 세션만 set | 다른 세션은 알림만 (예산 미충전) |
| 10 | `notify.enabled=false` + set | 알림 없이 grace 없이 즉시 wake (구 auto 동일) |
| 11 | `/cn:set 2` 가 **마지막 입력** (이후 turn 없음) → 방치 | 직전 fire 가 supersede 되지 않고 wake 진행 (메타 명령 activity 제외 가드 검증) |
| 12 | 신규 설치 (config.toml 없음) 첫 fire | 생성된 config 가 `arm="manual"` — `CLAUDE_PLUGIN_OPTION_MODE` 가 hybrid 를 시드하지 않음 |

## 부록 — 기획 결정 로그 (2026-06-10 grilling)

| Q | 결정 |
|---|---|
| set N 의미 | N = 허용 wake 횟수 |
| config 구조 | mode enum 폐기, 알림/wake 2축 + arm 정책 (하위호환 매핑) |
| 제품 방향 | 기본 = 알림 + set 소생. always 는 opt-in escape hatch |
| arm 기본값 / 이름 | `manual` (값 이름도 "manual") |
| set 범위 | 친 세션만 충전 |
| 복귀 시 예산 | 0 으로 소멸. 복귀 판정 = "충전 후 wake ≥1회 이후의 진짜 prompt" |
| manual+예산0 알림 | 울림 (살리지는 않음) |
| recap | 2줄 (예산 >0 시), 예산 0 이면 현행 1줄 |
| set 상한 | `min(N, max_refresh_count)` + 충전 응답에 안내 |
| fire_reset | 폐기 — arm 변경은 /cn:config 일원화 |
| 마이그레이션 | 동작 보존 매핑 + deprecated 경고 |
| ping (N/M) | manual 에서 M = 충전 예산 |

# cache-necromancer PRD

작성일: 2026-05-12 (KST)
v2 업데이트: 2026-05-13 — headless CLI 메커니즘으로 전환 (실험으로 검증 완료)
상태: 검토 대기

---

## 한 줄 요약

Claude Code의 프롬프트 캐시가 죽기 직전(1시간 TTL 만료 5분 전)에 백그라운드에서 최소 프롬프트 `.`을 자동 전송해서 캐시 수명을 1시간 연장하는 Claude Code 플러그인.

> 💀 **네크로맨서가 죽어가는 캐시를 부활시킨다.**

---

## 왜 만드는가

- Anthropic 프롬프트 캐시는 hit 시 토큰 비용이 정상의 **1/10 수준**.
- 캐시 TTL은 1시간. 사용자가 점심 먹거나 회의 들어가면 그대로 만료.
- 만료된 뒤 다시 작업하면 처음부터 fresh request → **돈 새는 소리**.
- "응답 끝나고 가만히 두면 캐시가 살아있을 텐데 그걸 살릴 수 있는 자동 도구"가 필요.
- 공개 Claude Code 플러그인으로 배포 예정 (Anthropic 공식 권장은 아닌 회색지대 도구. 사용자 책임 하에 사용).

---

## 핵심 메커니즘 (v2 변경)

Claude Code의 **headless CLI 기능**(`-p` + `--resume`)을 활용:

```bash
claude -p "." --resume <session_id> --fork-session --no-session-persistence
```

이 한 줄이:
1. **별도 프로세스로** Claude API에 짧은 요청 보냄 (사용자 인터랙티브 화면 안 건드림)
2. `--resume`으로 기존 session prefix 재사용 → Anthropic API 캐시 **hit** → TTL 갱신
3. `--fork-session`으로 원본 session JSONL은 건드리지 않음
4. `--no-session-persistence`로 fork된 session jsonl도 디스크에 남기지 않음

**실험 검증 결과** (2026-05-13):
- cache_read: **46,115 tokens** (거의 전체 prefix hit)
- cache_create: 40 tokens (거의 무비용)
- 원본 session jsonl: 변화 없음 ✅
- 디스크 흔적: 없음 ✅
- 비용: 캐시 hit 가격 = 정상 input의 10%

---

## 누구를 위한 도구인가

**1차 타겟 — 공개 plugin 사용자 (Claude Code 일반 사용자)**
- Claude Code를 자주/장시간 사용하면서 프롬프트 캐시 비용을 줄이고 싶은 모든 사용자
- 자리를 비우는 시간이 있어도 작업 컨텍스트가 캐시에 살아있길 원하는 사용자
- 여러 프로젝트를 동시에 띄워두고 오가는 사용 패턴

**2차 타겟 — 헤비 유저**
- Claude Code 상시 실행하는 1인 개발자 / 인디 해커
- 여러 에이전트를 병렬로 돌리는 사용자
- 비용 민감한 스타트업/팀

**환경 요구사항 (v1)**
- Claude Code v2.x 이상
- 운영체제: **macOS (1차)**, **Linux (알림 어댑터만 추가하면 즉시 가능)**
- 터미널 환경 제약 **없음** — tmux / iTerm / Terminal.app / VS Code 통합 터미널 / Ghostty / Alacritty / 무엇이든 동작

핵심: headless CLI 방식이라 **외부에서 터미널 PTY를 건드리지 않음**. 그래서 터미널 종류와 무관하게 동작.

---

## 유저 스토리

1. **As a Claude Code 사용자, 점심 먹으러 자리를 비웠는데** 캐시 만료 시점에 백그라운드에서 자동으로 캐시를 갱신해서 **돌아왔을 때도 캐시가 살아있길 원한다.** (auto 모드)

2. **As a 신중한 사용자, 캐시가 만료될 시점이 다가오면** 알림으로 알려주고 내가 직접 결정하길 원한다. (notify 모드)

3. **As a 둘 다 원하는 사용자, 임박 시점에 알림을 받고 60초 안에 응답하지 않으면** 자동 갱신되길 원한다. (hybrid 모드)

4. **As a 여러 프로젝트 동시 작업 사용자**, 각 Claude Code 세션마다 독립적으로 캐시 수명을 추적하길 원한다.

5. **As a 절약은 좋아하지만 무한 갱신은 위험한 사용자**, 갱신 횟수에 상한을 두고 (기본 10회 = 약 10시간) 그 이상은 자동 중지하길 원한다.

6. **As a 사용자, 내가 보는 Claude Code 화면이 자동 갱신 때문에 더럽혀지지 않길 원한다** — 백그라운드 호출이라 인터랙티브 세션 화면에 흔적 없음.

---

## 작동 시나리오

### 시나리오 1: auto 모드 — 점심 시간
```
12:00  Claude에게 "테스트 짜줘" 요청
12:00  Claude 응답 종료 → 캐시 생성 (TTL 13:00까지)
12:05  브로디 점심 외출
12:55  cache-necromancer 데몬이 백그라운드에서:
        claude -p "." --resume <session_id> --fork-session \
                      --no-session-persistence
       → 캐시 hit → TTL 갱신 (13:55까지)
       → 인터랙티브 세션 화면: 변화 없음
13:30  돌아와서 작업 재개 → 캐시 hit ✅ 비용 1/10
```

### 시나리오 2: notify 모드 — 결정권 유지
```
14:00  Claude 응답 종료
14:55  macOS 알림: "💀 5분 후 캐시 만료. 갱신 안 함"
14:55  브로디가 "그래도 작업해야지" 하고 다음 질문 입력
       → 정상 흐름 (캐시 자연 갱신)
```

### 시나리오 3: 횟수 한도 도달
```
다음날 02:00  refresh_count = 10 도달
02:00  log: "[limit] refresh cap reached, stop refreshing"
02:00  자동 갱신 중지. 다음 작업 시 새 캐시 생성.
```

### 시나리오 4: 사용자가 작업 중인 경우
```
14:50  사용자가 한창 작업 중 (last_user_input_at가 최근)
14:55  데몬: last_user_input_at > last_stop_at - threshold
        → 사용자 작업 중으로 판정
        → 갱신 트리거 안 함 (사용자가 어차피 곧 응답할 것)
14:56  사용자가 다음 질문 → 정상 캐시 hit
```

### 시나리오 5: 멀티 세션
```
세션 A (프로젝트 vdit, tmux 탭1): 12:30 마지막 응답
세션 B (프로젝트 luna, VS Code 통합 터미널): 12:45 마지막 응답
세션 C (프로젝트 work, iTerm 단독): 13:00 마지막 응답

데몬:
  13:25 세션 A 캐시 갱신
  13:40 세션 B 캐시 갱신
  13:55 세션 C 캐시 갱신

각 세션은 자기 환경 무관하게 독립적으로 갱신됨.
```

---

## 성공 지표

**개인 지표 (1주일 사용 후)**

| 지표 | 정의 | 목표 |
|---|---|---|
| **fire hit률** | cache-necromancer가 fire한 호출 중 `cache_read > 0` 발생 비율 | 95% 이상 |
| **전체 사용 hit률** (Phase 4 측정) | 사용자 인터랙티브 세션 전체 input 토큰 대비 cache_read 비율 | 80% 이상 |
| **Net saved** | Gross saved − Fire cost (아래 "절약 모델" 참조) | > 0 (음수면 fire 낭비) |
| 사용자 보이는 인터랙티브 세션 영향 | 0건 |
| 데몬 비정상 종료 / 좀비 프로세스 | 0건 |

**공개 배포 지표 (출시 후 1개월)**

| 지표 | 목표 |
|---|---|
| GitHub stars | 50+ |
| `/plugin install` 다운로드 수 | 100+ |
| Critical bug report | 0건 |
| 사용자 보고 환경 (macOS 13~15, linux 베타) | 모두 정상 |

### 절약 모델 (대시보드 계산 기반)

**언제 절약이 발생하나**:
- fire 자체는 절약 0 (단지 TTL 연장).
- **사용자가 자리 비운 후 돌아와 input 보낼 때 cache_read 발생** → 그 turn이 "necromancer 덕분에 살아있는 캐시 활용".
- fire를 여러 번 했어도 사용자 활용 turn 1번 = 절약 1회.

**계산 공식** (토큰 1개당 정상 input 단가를 1.0 단위로):

| 항목 | 계산 |
|---|---|
| **Gross saved** | Σ (사용자 활용 turn의 `cache_read` 토큰) × (1.0 − 0.1) |
| **Fire cost** | Σ (모든 fire의 `cache_create × 1.25 + cache_read × 0.1`) |
| **Net saved** | Gross saved − Fire cost |

**판정 규칙**:
- "사용자 활용 turn" = 직전 사용자 입력(`last_user_input_at`)이 N분 이상 전 (예: 55분) + 그 사이에 fire가 있었던 UserPromptSubmit.
- Net saved가 음수면 fire가 낭비된 것 (사용자가 안 돌아옴) → `max_refresh_count` 조정 신호.

**측정에 필요한 데이터** (v1 log에 기록):
- 매 fire: `timestamp | fire | sid | model | cache_read | cache_create | input | output`
- 매 user_turn (자리 비운 후 첫 input의 응답): `timestamp | user_turn | sid | model | cache_read | cache_create | input | output | after_fire=true|false`

이 raw log만 v1에서 정확히 기록하면 Phase 4 대시보드는 후처리(파싱 + 가격 테이블 곱)만으로 모든 지표 계산 가능. 데이터 구조(SQLite/JSON)는 Phase 4에서 실제 사용 데이터 보고 결정.

---

## 무엇을 만드는가 (범위)

**Phase 1 — 기반 (PR 1개, ~200줄)**
- `.claude-plugin/plugin.json`, `hooks/hooks.json` 매니페스트
- Hook 3개 (Stop / UserPromptSubmit / SessionEnd) — timestamp 추적용
- 세션별 상태 추적 (JSON 파일 + atomic write + flock)
- macOS 알림 (`osascript`) + 터미널 벨
- 데몬 lifecycle (lazy 기동, lockfile, stale PID 처리)
- `notify` 모드 동작
- **fire log 한 줄 기록** (timestamp / sid / model / cache_read / cache_create / input / output) — Phase 4 대시보드의 raw 데이터
- 사용자용 `README.md`

**Phase 2 — 자동 갱신 (PR 1개, ~150줄)**
- `claude -p` 호출 wrapper
- `auto` 모드 동작
- `hybrid` 모드 (알림 → 대기 → 자동 갱신)
- macOS sleep/wake 감지 + 5분 유예
- fire 후 watchdog (silent 정지 방지)
- 갱신 성공/실패 결과 cache_read 토큰 측정으로 검증
- **user_turn log 기록** (UserPromptSubmit 발화 시점 + 대응 Stop hook에서 transcript jsonl 마지막 turn usage 추출) — `after_fire=true|false` 판정 포함

**Phase 3 — 공개 배포 준비 (PR 1개)**
- Anthropic Claude Code plugin marketplace 등록 (`.claude-plugin/marketplace.json`)
- `/plugin install` 한 줄 설치
- `userConfig` 활용한 첫 설치 시 모드 안내 (선택)
- 라이센스 (MIT), CHANGELOG, 이슈 템플릿
- 데모 GIF / 영상 (선택)

**Phase 4 — 통계/대시보드 (별도 spec, v0.2 이후)**
- v1 log 파싱 → Gross saved / Fire cost / Net saved 집계
- 모델별 가격 테이블 (시세 변동 대응, 별도 reference 파일)
- 일별 / 주별 절감 비용 차트
- 갱신 히스토리 / 시간대별 사용 패턴
- Linux 알림 어댑터 (notify-send)

---

## 무엇은 안 만드는가 (Out of Scope, v1 기준)

- ❌ **Windows 지원** — v2 이후 커뮤니티 PR 검토
- ❌ **transcript 통계 집계 / 대시보드** — Phase 4. v1은 raw log만 남김
- ❌ **Discord/Slack 외부 채널 통합** — 사용자가 직접 자기 hook으로 통합 (다른 Stop hook과 공존 가능)
- ❌ **GUI / 웹 대시보드**
- ❌ **인터랙티브 세션 화면에 시각적 카운트다운** — 백그라운드 동작이라 시각 표시 없음. 알림으로만 인지.

> **v1 변경점 (v2 PRD 업데이트)**: tmux 의존성 / 터미널 환경별 어댑터 / AppleScript 권한 요청 — 모두 불필요해짐. headless CLI 메커니즘이 환경 독립.

---

## 사용자 설정 (`~/.cache-necromancer/config.toml`)

| 설정 | 기본값 | 설명 |
|---|---|---|
| `mode` | `hybrid` | `notify` / `auto` / `hybrid` 중 하나 |
| `refresh_interval_minutes` | `55` | 캐시 갱신 시점 (TTL 1시간 - 5분 마진) |
| `max_refresh_count` | `10` | 자동 갱신 횟수 한도 (≈10시간) |
| `hybrid_wait_seconds` | `60` | hybrid 모드 알림 후 대기 시간 |
| `prompt` | `"."` | 전송할 최소 프롬프트 |
| `extra_claude_flags` | `"--fork-session --no-session-persistence"` | claude CLI 추가 플래그 |

상세 설정은 TECH_SPEC 참조.

---

## 안전 보장 정책 (v2 변경: PTY 관련 항목 → headless 관련으로 교체)

1. **사용자 인터랙티브 세션은 절대 건드리지 않음** — `claude -p` 별도 프로세스. `--fork-session`으로 원본 jsonl 보호.
2. **fork된 임시 session 디스크에 안 남김** — `--no-session-persistence`.
3. **사용자가 작업 중일 땐 갱신 안 함** — `last_user_input_at` vs `last_stop_at` 비교. 사용자가 응답 중이면 데몬이 알아서 대기.
4. **macOS sleep/wake 후 일제히 갱신 안 함** — `time.monotonic()` 드리프트 감지 후 5분 유예. 한꺼번에 여러 세션 토큰 비용 폭증 방지.
5. **갱신 횟수 한도 도달 시 자동 중지** — 무한 갱신으로 비용 폭증 방지.
6. **Hook이 실패해도 Claude Code 동작에 영향 없음** — 모든 hook은 항상 `exit 0`, stdout 비움.
7. **claude CLI 호출 실패 시 silent fallback** — 네트워크/인증 오류 시 log 기록 후 다음 사이클 재시도. 사용자 작업에 영향 없음.
8. **갱신 성공 검증** — `cache_read_input_tokens > 0`으로 실제 hit 발생 확인. 0이면 log 경고 (캐시 만료된 후 fire였을 수 있음).

---

## 관련 문서

- **TECH_SPEC v5 (작성 예정)**: `2026-05-12-cache-necromancer-design-v5.md` — headless CLI 기반 구현 명세
- **TECH_SPEC v4 (legacy)**: `2026-05-12-cache-necromancer-design-v4.md` — PTY 주입 기반 (참고용, 폐기 예정)
- **PLAN**: writing-plans 스킬로 작성 예정

---

## 검토 포인트 (브로디용)

이 PRD에 대해 답해주세요:

1. **메커니즘 설명**이 명확한가? (headless CLI가 왜 우월한지)
2. **타겟 사용자 확장**이 적절한가? (tmux 제약 사라짐)
3. **시나리오 5개** 중 빠뜨린 케이스 있는가? (특히 멀티 세션 / 사용자 작업 중)
4. **성공 지표 목표값**이 합리적인가?
5. **범위**(Phase 1 + 2)가 적절한가? Phase 3(공개 배포)도 v1 출시에 포함 OK인가?
6. **안전 보장 8가지**로 충분한가?
7. **Out of Scope** 중 사실은 포함해야 할 게 있는가?

OK 사인 주시면 TECH_SPEC v5 작성으로 진행합니다.

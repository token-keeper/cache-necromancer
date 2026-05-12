# cache-necromancer PRD

작성일: 2026-05-12 (KST)
v2 업데이트: 2026-05-13 — headless CLI 메커니즘으로 전환 (실험으로 검증 완료)
v3 업데이트: 2026-05-13 — codex PRD 리뷰 반영 (공개 plugin 신뢰성 보강)
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

**왜 안전한가 (사용자 관점 3문장)**

1. **무엇을 읽나** — Claude Code가 이미 디스크에 저장해둔 당신의 session JSONL(`~/.claude/projects/.../<id>.jsonl`)을 읽기만 함. 외부 서버로 아무것도 보내지 않음.
2. **무엇을 보내나** — 당신의 기존 대화 prefix + 짧은 `.` 문자 한 글자를 Anthropic API에 보냄 (당신이 평소 Claude를 쓸 때 보내는 것과 동일한 데이터, 추가 정보 없음).
3. **무엇을 절대 수정 안 하나** — 원본 session JSONL, 인터랙티브 화면, 다른 Claude Code 설정. fork session은 한 번 쓰고 디스크에 안 남김 (`--no-session-persistence`).

---

## 누구를 위한 도구인가

**1차 타겟 — 큰 컨텍스트를 유지한 채 자리 비웠다 1시간 안팎으로 복귀하는 Claude Code 사용자**
- 한 세션에서 **수만 토큰 prefix**(긴 대화, 큰 코드베이스, 두꺼운 system prompt)를 쌓아둔 상태
- 점심, 회의, 짧은 외출, 오후 작업 마무리 등 **자리 비움 패턴이 일과에 자주 있음**
- 돌아왔을 때 같은 컨텍스트를 이어가는 패턴 (새 세션 시작이 아님)
- 자리 비움 간격이 1시간 안팎이라 1회 갱신만으로 큰 효과

**2차 타겟 — 헤비 유저**
- Claude Code 상시 실행하는 1인 개발자 / 인디 해커
- 여러 에이전트를 병렬로 돌리는 사용자
- 비용 민감한 스타트업/팀

### 추천 / 비추천 사용 패턴

| 패턴 | 추천 여부 | 이유 |
|---|---|---|
| 점심/회의 후 같은 컨텍스트로 돌아옴, prefix > 10K 토큰 | ✅ 강력 추천 | Net saved 명확히 양수 |
| 하루 종일 띄워두는 상시 세션 | ✅ 추천 | `max_refresh_count` 한도 안에서 안정적 절약 |
| 자리 비움이 1시간 이내가 대부분 | 🟡 보통 | 갱신 안 해도 캐시 살아있음 → 효과 작음 |
| 한 번 작업하고 다음날까지 안 돌아옴 | ❌ 비추천 | fire 비용만 누적, Net saved < 0 위험 |
| 매번 새 프로젝트/새 세션 시작 패턴 | ❌ 비추천 | 캐시 hit 자체가 잘 안 됨 |
| Windows 환경 | ❌ 미지원 | v2 이후 커뮤니티 PR 검토 |

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

7. **As a 처음 설치한 사용자, "이 플러그인이 내 세션을 진짜 안 건드리는지" 직접 확인하고 싶다** — `/cn:status` 명령으로 추적 중인 세션 / 다음 갱신 시각 / 직전 fire 결과를 볼 수 있고, `/cn:dry-run` 명령으로 실제 fire 안 하고 시뮬레이션만 가능. `~/.cache-necromancer/daemon.log`에서 어떤 명령이 언제 실행됐는지 모두 확인 가능.

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

### 시나리오 4: 멀티 세션
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

### 시나리오 5: 중복 데몬 / 동일 세션 동시 추적 방지
```
12:00  Claude Code 세션 A 응답 → 데몬1 spawn
12:05  사용자가 같은 터미널을 실수로 재시작 → 데몬2 spawn 시도
12:05  데몬2: ~/.cache-necromancer/daemon.lock 획득 시도
        → 데몬1 PID 살아있음 확인 (os.kill(pid, 0))
        → 즉시 종료 (단일 owner만 폴링)
12:55  데몬1만 세션 A에 fire (한 번만)
```
중복 fire로 인한 비용 폭증 방지. lockfile에 PID + start_time 함께 기록해 PID 재사용으로 인한 오인도 차단.

### 시나리오 6: 1시간 이상 자리 비웠다 돌아온 경우 (이미 캐시 만료)
```
12:00  Claude 응답 종료, TTL 13:00
12:55  데몬 fire 시도 (정상)
        → cache_read=45,000 → 성공, TTL 13:55
        → refresh_count = 1
13:50  fire 또 시도, TTL 14:50
        ...
다음날 02:00  refresh_count = 10 도달 (max 한도)
02:00  fire 중지. log: "[limit] refresh cap reached"
        TTL 자연 만료, 캐시 사라짐.
다음날 09:00  사용자 출근, 같은 세션에서 작업 재개
        → cache_read=0 (캐시 만료 후 첫 요청)
        → 데몬: log "[expired] sid=... cache cold at first turn"
        → 새 캐시 생성 (정상 비용)
        → 이후 사이클은 정상 작동
```
자리 비움이 너무 길어 캐시가 이미 죽었을 땐 별도 사고 없이 새 캐시로 정상 복귀. 비용은 정상 1회분만 추가됨.

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

**Output 토큰 비용은 의도적으로 제외**. 이유: fire가 보내는 `.` 응답의 output은 매번 거의 동일한 짧은 응답(예: 50~250 토큰)이고, 사용자가 실제로 작업할 때의 output과 무관함. cache-necromancer가 절약하는 건 input prefix 비용이지 output이 아님. Phase 4 대시보드에서 "참고용 fire output 합계"는 별도로 표시할 수 있지만 Net saved 계산엔 포함 안 함.

**판정 규칙**:
- "사용자 활용 turn" = 직전 사용자 입력(`last_user_input_at`)이 N분 이상 전 (예: 55분) + 그 사이에 fire가 있었던 UserPromptSubmit.
- Net saved가 음수면 fire가 낭비된 것 (사용자가 안 돌아옴) → 사용 패턴 재검토 신호.

### Net saved < 0일 때 사용자 조치 (단계별 권고)

대시보드(Phase 4) 또는 `/cn:status` 명령이 Net saved 음수를 감지하면 다음 권고를 표시:

| 패턴 | 권고 |
|---|---|
| 사용자 활용 turn이 거의 없음 (fire 10번, 활용 1번 미만) | **mode를 `notify`로 전환** — 자동 fire 끄고 알림만 받기 |
| 사용자 활용은 있지만 fire 비율이 과함 (예: fire 20번, 활용 3번) | **`max_refresh_count` 감소** (10 → 5) |
| 자리 비움 시간이 보통 1시간 이내 (자연 캐시 hit) | **플러그인 비활성화 권고** — 이미 자연스럽게 캐시 활용 중이라 도구 불필요 |
| 첫 fire가 매번 `cache_read=0` | **세션 사용 패턴 점검** — 매번 새 세션 시작이면 캐시 갱신 의미 없음 |

자동 조치 없음 — 사용자가 보고 직접 조정. 데몬은 어떤 경우에도 mode를 사용자 동의 없이 바꾸지 않음.

**측정에 필요한 데이터** (v1 log에 기록):
- 매 fire: `timestamp | fire | sid | model | cache_read | cache_create | input | output`
- 매 user_turn (자리 비운 후 첫 input의 응답): `timestamp | user_turn | sid | model | cache_read | cache_create | input | output | after_fire=true|false`

이 raw log만 v1에서 정확히 기록하면 Phase 4 대시보드는 후처리(파싱 + 가격 테이블 곱)만으로 모든 지표 계산 가능. 데이터 구조(SQLite/JSON)는 Phase 4에서 실제 사용 데이터 보고 결정.

---

## 무엇을 만드는가 (범위)

### 출시 컷

> **v1 = Phase 1 + Phase 2 + Phase 3 (release hardening 포함)**
> Phase 4(통계/대시보드)는 **v0.2** 이후 별도 spec.

**Phase 1 — 기반 (PR 1개, ~200줄)**
- `.claude-plugin/plugin.json`, `hooks/hooks.json` 매니페스트
- Hook 3개 (Stop / UserPromptSubmit / SessionEnd) — timestamp 추적용
- 세션별 상태 추적 (JSON 파일 + atomic write + flock)
- macOS 알림 (`osascript`) + 터미널 벨
- 데몬 lifecycle (lazy 기동, lockfile, stale PID 처리)
- `notify` 모드 동작
- `/cn:status` 명령 (추적 중인 세션 / 다음 갱신 시각 / 직전 fire 결과 표시)
- **fire log 한 줄 기록** (timestamp / sid / model / cache_read / cache_create / input / output) — Phase 4 대시보드의 raw 데이터
- 사용자용 `README.md`
- **검증 가능한 것**: 사용자가 점심 후 돌아왔을 때 macOS 알림으로 임박 시점을 인지함. `/cn:status`로 추적 상태 확인.

**Phase 2 — 자동 갱신 (PR 1개, ~150줄)**
- `claude -p` 호출 wrapper
- `auto` 모드 동작
- `hybrid` 모드 (알림 → 대기 → 자동 갱신)
- macOS sleep/wake 감지 + 5분 유예
- fire 후 watchdog (silent 정지 방지)
- 갱신 성공/실패 결과 cache_read 토큰 측정으로 검증
- 연속 fire 실패 N회 시 사용자 알림 (인지 가능한 실패)
- `/cn:dry-run` 명령 (실제 fire 안 하고 시뮬레이션)
- **user_turn log 기록** (UserPromptSubmit 발화 시점 + 대응 Stop hook에서 transcript jsonl 마지막 turn usage 추출) — `after_fire=true|false` 판정 포함
- **검증 가능한 것**: 자리 비웠다 돌아오면 cache_read > 0 으로 캐시 활용 확인. log에서 갱신 비용 추적 가능.

**Phase 3 — 공개 배포 준비 (PR 1개)**
- Anthropic Claude Code plugin marketplace 등록 (`.claude-plugin/marketplace.json`)
- `/plugin install` 한 줄 설치
- `userConfig` 활용한 첫 설치 시 모드 안내
- 라이센스 (MIT), CHANGELOG, 이슈 템플릿
- 데모 GIF / 영상 (선택)
- README에 "추천/비추천 사용 패턴" + "안전성 확인 방법" 명시
- **검증 가능한 것**: 외부 사용자가 `/plugin install`로 설치 후 README만 보고 안전하게 사용 시작.

**Phase 4 — 통계/대시보드 (별도 spec, v0.2 이후)**
- v1 log 파싱 → Gross saved / Fire cost / Net saved 집계
- 모델별 가격 테이블 (시세 변동 대응, 별도 reference 파일)
- 일별 / 주별 절감 비용 차트
- 갱신 히스토리 / 시간대별 사용 패턴
- Net saved < 0 시 사용자에게 권고 메시지 표시
- Linux 알림 어댑터 (notify-send)
- **검증 가능한 것**: 사용자가 1주일 사용 후 실제 절약 금액 + 자기 패턴이 추천/비추천 중 어느 쪽인지 확인.

---

## 무엇은 안 만드는가 (Out of Scope, v1 기준)

- ❌ **Windows 지원** — v2 이후 커뮤니티 PR 검토
- ❌ **transcript 통계 집계 / 대시보드** — Phase 4. v1은 raw log만 남김
- ❌ **Discord/Slack 외부 채널 통합** — 사용자가 직접 자기 hook으로 통합 (다른 Stop hook과 공존 가능)
- ❌ **GUI / 웹 대시보드**
- ❌ **인터랙티브 세션 화면에 시각적 카운트다운** — 백그라운드 동작이라 시각 표시 없음. 알림으로만 인지.
- ❌ **자동 비용 최적화 / 모델별 동적 의사결정** — v1은 단순 시간 기반 fire만. "사용 패턴 분석해서 fire 시점/빈도 자동 조정"이나 "모델별 fire 가치 계산 후 전략 변경" 같은 지능형 튜닝은 미포함.

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

## 안전 보장 정책 (v3)

### 데이터 / 세션 보호
1. **사용자 인터랙티브 세션은 절대 건드리지 않음** — `claude -p` 별도 프로세스. `--fork-session`으로 원본 jsonl 보호.
2. **fork된 임시 session 디스크에 안 남김** — `--no-session-persistence`.
3. **외부 서버 전송 없음** — 100% 로컬 동작. session JSONL 데이터는 Anthropic API로만 전송 (당신이 평소 Claude Code 쓸 때와 동일).

### 비용 폭증 방지
4. **사용자가 작업 중일 땐 갱신 안 함** — `last_user_input_at` vs `last_stop_at` 비교.
5. **macOS sleep/wake 후 일제히 갱신 안 함** — `time.monotonic()` 드리프트 감지 후 5분 유예.
6. **갱신 횟수 한도 자동 중지** — `max_refresh_count` (기본 10) 도달 시 자동 멈춤.
7. **중복 데몬 차단** — lockfile + PID start_time으로 단일 인스턴스 보장. PID 재사용 오인 방지.

### 인지 가능한 실패 (silent failure 방지)
8. **연속 fire 실패 시 사용자 알림** — 3회 연속 fire가 `cache_read=0` 또는 에러 → macOS 알림으로 사용자에게 알림. 5회 도달 시 해당 세션 자동 비활성화 + 알림.
9. **상태 확인 명령 제공** — `/cn:status`로 추적 중인 세션 / 다음 갱신 시각 / 직전 결과 / 누적 fire 비용 확인 가능. 사용자가 언제든 상태를 체크.
10. **Hook이 실패해도 Claude Code 동작에 영향 없음** — 모든 hook은 항상 `exit 0`, stdout 비움. 단, 데몬 spawn 실패는 일별 1회 알림으로 사용자에게 통지.

### 갱신 검증
11. **`cache_read > 0`으로 hit 확인** — fire 응답에서 cache_read 토큰이 0이면 캐시가 이미 만료된 상태 → log 경고 + 해당 세션 다음 사이클 중단(이미 cold이므로 더 fire해도 의미 없음).

### Raw log 민감정보 처리 (공개 plugin 신뢰성)
12. **log 저장 위치 / 필드 / 보존 기간 명시**:
    - 위치: `~/.cache-necromancer/daemon.log.YYYY-MM-DD` (사용자 홈 디렉토리, 외부 전송 없음).
    - 기록 필드: timestamp, sid_hash (실제 session_id 아닌 sha256 hash), model명, 토큰 수 4종.
    - **사용자 프롬프트 내용, 응답 본문, 파일 경로, cwd 절대 기록 안 함**.
    - 보존: 7일 후 자동 삭제. 사용자가 즉시 삭제하려면 `rm ~/.cache-necromancer/daemon.log.*`.

---

## 관련 문서

- **TECH_SPEC v5 (작성 예정)**: `2026-05-12-cache-necromancer-design-v5.md` — headless CLI 기반 구현 명세
- **TECH_SPEC v4 (legacy)**: `2026-05-12-cache-necromancer-design-v4.md` — PTY 주입 기반 (참고용, 폐기 예정)
- **PLAN**: writing-plans 스킬로 작성 예정

---

## 검토 포인트 (브로디용, v3)

1. **메커니즘 + "왜 안전한가" 3문장** — 일반 사용자가 충분히 이해할 수 있는가?
2. **추천/비추천 사용 패턴 표** — 정확하고 사용자가 자기 판단에 활용 가능한가?
3. **유저 스토리 7개** + **시나리오 6개** — 빠뜨린 케이스 있는가?
4. **절약 모델 + Net < 0 권고** — 사용자가 자기 데이터 보고 행동 결정 가능한가?
5. **v1 출시 컷 (Phase 1+2+3) + Phase별 검증 가능한 것** — 출시 경계 명확한가?
6. **안전 보장 12가지** — 데이터/비용/실패 인지/log 민감정보 4영역 다 충분한가?
7. **Out of Scope** — 자동 비용 최적화 명시까지 OK?

OK 사인 주시면 TECH_SPEC v5 작성으로 진행합니다.

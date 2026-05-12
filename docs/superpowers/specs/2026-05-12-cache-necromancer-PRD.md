# cache-necromancer PRD

작성일: 2026-05-12 (KST)
상태: 검토 대기

---

## 한 줄 요약

Claude Code의 프롬프트 캐시가 죽기 직전(1시간 TTL 만료 5분 전)에 최소 프롬프트 `.`을 자동 주입해서 캐시 수명을 1시간 연장하는 macOS용 Claude Code 플러그인.

> 💀 **네크로맨서가 죽어가는 캐시를 부활시킨다.**

---

## 왜 만드는가

- Anthropic 프롬프트 캐시는 hit 시 토큰 비용이 1/10 수준으로 떨어짐.
- 캐시 TTL은 1시간. 사용자가 점심 먹거나 회의 들어가면 그대로 만료.
- 만료된 뒤 다시 작업하면 처음부터 fresh request → **돈 새는 소리**.
- "응답 끝나고 가만히 두면 캐시가 마지막에 1분 + 1초 더 살아있을 텐데 그걸 살릴 수 있는 자동 도구"가 필요.
- 개인 사용 목적. Anthropic 공식 권장은 아닌 회색지대.

---

## 누구를 위한 도구인가

- macOS + iTerm2 + tmux 환경에서 Claude Code를 상시 띄워두는 개발자 (= 브로디 본인)
- 여러 프로젝트를 tmux 탭에 띄워두고 오가는 사용 패턴
- 캐시 비용에 민감하고, 자동화로 비용 절감을 보고 싶은 사람

---

## 유저 스토리

1. **As a Claude Code 사용자, 점심 먹으러 자리를 비웠는데** 캐시 만료 시점에 자동으로 `.` 한 글자를 주입해서 **돌아왔을 때도 캐시가 살아있길 원한다.** (auto 모드)

2. **As a 신중한 사용자, 캐시가 만료될 시점이 다가오면** macOS 알림으로 알려주고 내가 직접 결정하길 원한다. (notify 모드)

3. **As a 둘 다 원하는 사용자, 임박 시점에 알림을 받고 60초 안에 내가 응답하지 않으면** 자동 갱신되길 원한다. (hybrid 모드)

4. **As a 여러 프로젝트 동시 작업 사용자**, 각 tmux 탭마다 독립적으로 캐시 수명을 추적하길 원한다.

5. **As a 절약은 좋아하지만 무한 갱신은 위험한 사용자**, 갱신 횟수에 상한을 두고 (기본 10회 = 약 10시간) 그 이상은 자동 중지하길 원한다.

---

## 작동 시나리오 (사용자가 체감하는 흐름)

### 시나리오 1: auto 모드 — 점심 시간
```
12:00  Claude에게 "테스트 짜줘" 요청
12:00  Claude 응답 종료 → 캐시 생성 (TTL 13:00까지)
12:05  브로디 점심 먹으러 외출
12:55  cache-necromancer가 tmux pane 상태 확인 후 "." 자동 입력
12:55  Claude가 짧은 응답 → 캐시 갱신 (TTL 13:55까지)
13:30  돌아와서 작업 재개 → 캐시 hit ✅
```

### 시나리오 2: notify 모드 — 결정권 유지
```
14:00  Claude 응답 종료
14:55  macOS 알림: "💀 5분 후 캐시 만료. 갱신 트리거 안 함"
14:55  브로디가 "그래도 작업해야지" 하고 다음 질문 입력 → 정상 흐름
```

### 시나리오 3: 횟수 한도 도달
```
다음날 02:00  refresh_count = 10에 도달
02:00  log: "[limit] refresh cap reached, stop refreshing"
02:00  더 이상 자동 갱신 안 함. 다음 작업 시 새 캐시 생성.
```

### 시나리오 4: 안전 보장 — 사용자 타이핑 중
```
14:50  브로디가 답변 작성 중 (Enter 안 눌렀음)
14:55  cache-necromancer가 fire 시도
        → tmux pane buffer가 비어있지 않음 감지
        → "." 주입 취소, 다음 폴링 사이클에 재시도
14:56  브로디가 입력 완료 후 Enter → 사용자 입력으로 인식, 타이머 리셋
```

---

## 성공 지표 (1주일 사용 후)

| 지표 | 목표 |
|---|---|
| 캐시 hit rate (cache_read_input_tokens / 전체) | 60% 이상 |
| 자동 갱신 성공률 (fire 시도 대비 OK) | 95% 이상 |
| 잘못된 주입 사고 (사용자 입력 중 `.` 끼어듦) | 0건 |
| 데몬 비정상 종료 / 좀비 프로세스 | 0건 |

---

## 무엇을 만드는가 (범위)

**Phase 1 — 기반 (PR 1개)**
- `.claude-plugin/plugin.json`, `hooks/hooks.json` 매니페스트
- Hook 3개 (Stop / UserPromptSubmit / SessionEnd)
- 세션별 상태 추적 (JSON 파일)
- macOS 알림 + 터미널 벨
- `notify` 모드 동작
- 데몬 자체 lifecycle 관리 (lazy 기동, lockfile)

**Phase 2 — 자동 주입 (PR 1개)**
- `tmux send-keys "."` 안전 주입 (5단계 검증)
- `auto` 모드 동작
- `hybrid` 모드 동작 (알림 → 대기 → 자동 갱신)
- macOS sleep/wake 보정
- fire 후 watchdog (silent 정지 방지)

**Phase 3 — 통계/대시보드 (별도 spec, 차후)**
- 절약 토큰 추정
- 갱신 히스토리

---

## 무엇은 안 만드는가 (Out of Scope)

- ❌ Linux/Windows 지원 (macOS 전용)
- ❌ tmux 외부 환경 (iTerm 단독, VS Code 통합 터미널 등) — `$TMUX` 없으면 비활성
- ❌ 캐시 hit 직접 측정 — Anthropic API 응답 metric 별도 조회 안 함, log 기반 추정만
- ❌ Discord/Slack 같은 외부 채널 통합 (기존 Stop hook으로 이미 구성된 게 있음)
- ❌ tmux 상태바 카운트다운 — macOS 알림 + 벨만 사용
- ❌ statusline.py 통합 — 별도 도구로 독립
- ❌ GUI / 웹 대시보드

---

## 사용자 설정 (`~/.cache-necromancer/config.toml`)

브로디가 바꿀 가능성이 있는 주요 값:

| 설정 | 기본값 | 설명 |
|---|---|---|
| `mode` | `hybrid` | `notify` / `auto` / `hybrid` 중 하나 |
| `refresh_interval_minutes` | `55` | 캐시 갱신 시점 (TTL 1시간 - 5분 마진) |
| `max_refresh_count` | `10` | 자동 갱신 횟수 한도 (≈10시간) |
| `hybrid_wait_seconds` | `60` | hybrid 모드 알림 후 대기 시간 |
| `prompt` | `"."` | 주입할 최소 프롬프트 |

상세 설정은 TECH_SPEC 참조.

---

## 안전 보장 정책

1. **사용자 타이핑 중일 땐 절대 fire 안 함** — tmux pane buffer 마지막 줄 검사.
2. **Claude 프로세스가 죽으면 즉시 비활성화** — pane PID liveness 체크.
3. **잘못된 주입이 무한 반복되지 않음** — send-keys 3회 연속 실패 시 해당 세션 비활성화.
4. **macOS sleep/wake 후 일제히 fire 안 함** — `time.monotonic` 기반 드리프트 감지 후 5분 유예.
5. **갱신 횟수 한도 도달 시 자동 중지** — 무한 갱신으로 인한 비용 폭증 방지.
6. **Hook이 실패해도 Claude Code 동작에 영향 없음** — 모든 hook은 항상 exit 0, stdout 비움.

---

## 관련 문서

- **TECH_SPEC**: `2026-05-12-cache-necromancer-design-v4.md` (구현 의사코드, 1100줄 — 구현자/리뷰어용)
- **PLAN**: writing-plans 스킬로 작성 예정 (Phase 1, 2 task 분해)

---

## 검토 포인트 (브로디용)

이 PRD에 대해 답해주시면 됩니다:

1. **목적/유저 스토리/시나리오**가 의도한 동작과 맞는가?
2. **성공 지표 목표값**이 합리적인가? (cache hit rate 60%, fire 성공률 95%)
3. **범위**(Phase 1 + Phase 2)가 적절한가, 더 줄이거나 늘릴 게 있는가?
4. **out of scope 항목** 중에서 사실은 포함해야 할 게 있는가?
5. **안전 보장 정책 6가지**로 충분한가?

OK 사인 주시면 TECH_SPEC도 같이 승인된 걸로 보고 PLAN(구현 task 분해) 단계로 진행합니다.

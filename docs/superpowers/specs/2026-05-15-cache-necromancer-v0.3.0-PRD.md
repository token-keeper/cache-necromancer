# cache-necromancer v0.3.0 — PRD

> **Status**: Draft (작성 2026-05-15)
> **Author**: Brody Byun
> **Related**: [TECH_SPEC](2026-05-15-cache-necromancer-v0.3.0-TECH_SPEC.md), [PLAN](../plans/2026-05-15-cache-necromancer-v0.3.0-PLAN.md)
> **Supersedes**: v0.2.x daemon-based fire architecture

## 1. 한 줄 요약

cache-necromancer 의 메커니즘을 외부 `claude -p` fire (subprocess) 에서 Claude Code 의 native Stop hook + `asyncRewake` 로 전환. chat 세션 자체가 idle 상태에서 자기 자신을 깨워 cache TTL 갱신.

## 2. 배경

### 2.1 v0.2.x 의 fundamental 결함

**v0.2.x architecture**: 별도 Python daemon 이 사용자 chat 의 sid 를 추적해 만료 직전 `claude -p --resume <sid> --fork-session --no-session-persistence` 로 외부 fire.

**진단 결과** (2026-05-15 Test 1~8): `claude -p` mode 와 chat mode 의 system prompt 가 byte 단위로 다름. Anthropic prompt cache 는 prefix hash 기반이라 system 부터 다르면 cache namespace 가 분리. **fire 가 chat 의 cache TTL 을 절대 갱신할 수 없음**.

```
Test 8 evidence:
chat turn 5 cache_read = 17,601 (chat system) + 25,102 (chat turn 1 cache) = 42,703
                        ≠ 18,833 + 27,476 (fire turn 4 의 cache)
→ chat 은 자기 cache 만 hit. fire cache 는 무시
```

도구의 fundamental 가정 ("외부 fire 가 chat cache 갱신") 자체가 틀림.

### 2.2 fix 발견 — `asyncRewake`

Claude Code hook 의 공식 field `asyncRewake: true` 사용 시 hook script 가 background 에서 sleep 한 후 stderr 출력 + exit 2 로 종료 → Claude Code 가 chat 세션을 깨워 hook stderr 를 새 user-role message 로 transcript 에 추가 → 모델이 응답하는 새 turn 발생.

**핵심 차이**: chat 세션 프로세스 자체 안에서 turn 발사. system prompt + tools 가 byte-exact 보존 → cache prefix hit.

**검증 결과**:
- 작은 transcript (27K): turn 2 cc=143 / cr=44,778 = 100% hit
- 1M context: 두 번째 wake cc=586 / cr=153,700 / $0.085 = **94% 비용 절감**
- 30분 sleep 후 wake: cr=44.55K = **30분 cache 100% 보존 확인** (1h cache 사용)

## 3. 사용자 가치

### 3.1 문제 (변경 없음)

사용자가 작업 도중 자리를 비울 때 (회의·점심·식사) 1시간 prompt cache 가 만료되어, 돌아와 다음 message 보내면 cache 재구축 비용이 발생.
- 1M context 기준: 만료 후 첫 message ~$1+ (rebuild) → 정상 message 의 10배

### 3.2 해결 (v0.3.0)

cache-necromancer 가 사용자 chat 의 idle 상태를 감지해 cache TTL 만료 직전 (default 50분 후) 자동으로 **최소한의 ping turn** (수백 token, 모델 응답 1-2 token) 을 발사하여 cache 를 살려둠. wake-up turn 평균 비용 ≤ $0.10 (Opus 1M ctx).

사용자는 `mode` 설정으로 동작 강도 조절:
- `notify`: 알림만 띄우고 wake X (cache 갱신 안 함, 비용 0). 자동 비용 발생 싫은 사용자
- `auto`: 자동 wake (default). 비용 발생, cache 100% 보존
- `hybrid`: 알림 → `hybrid_wait_seconds` 추가 sleep → 사용자 input 없으면 wake. 알림 받고 직접 돌아올 기회 + 그래도 자리 비우면 자동 보존

### 3.3 사용자 시나리오 (default `auto` mode)

```
1. 사용자가 cache-necromancer plugin 설치 (/plugin install cache-necromancer)
2. (중요) 새 Claude Code 세션 시작 — settings hot-reload 안 되므로 기존 세션은 적용 X
3. 평소처럼 Claude Code 사용 — 매 turn 끝마다 hook 등록되며 가장 최근 turn 기준 50분 sleep
4. 자리 비움 → 50분 후 chat 에서 자동으로 짧은 keep-alive turn 발생
5. 사용자 돌아와 message 입력 → cache hit, 비용 발생 없음
```

`hybrid` mode 차이: 4단계에서 50분 sleep → macOS 알림 → `hybrid_wait_seconds` (default 60s) 추가 sleep → 그 사이 사용자가 chat 에 input 하면 wake skip / 없으면 wake.

`notify` mode: 4단계에서 알림만 (wake X). 사용자가 직접 돌아오지 않으면 cache 만료.

## 4. 성공 지표

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| Wake 후 cache hit rate | ≥ 95% | 별도 분석 스크립트 (수동): jsonl 의 wake-up assistant turn (= `<task-notification>` user message 직후) 의 `cache_read_input_tokens` / 직전 user turn 의 assistant 응답에서 누적 `cache_creation_input_tokens` 합산 |
| Wake-up turn 평균 비용 | ≤ $0.10 (Opus 1M ctx) | 위 분석 스크립트의 wake-up turn `costUSD` 평균 |
| Cache rebuild 회피율 | ≥ 90% (사용자 자리비움 1h 케이스) | 사용자 input gap > 1h 인 케이스에서 다음 turn 의 `cache_read` 가 hit/miss |
| 설치 명령 단순성 | `/plugin install cache-necromancer` 한 명령으로 등록 + 새 세션부터 동작 (acceptance criteria) | 신규 환경에서 manual smoke test |
| 데몬 의존성 | 0 (no Python daemon, no lock dir) | code audit |

## 5. Scope

### 5.1 In scope

- Plugin manifest 기반 hook 자동 등록 (`/plugin install` 한 명령으로 활성화)
- Stop hook + `asyncRewake` 로 chat 자체 wake
- 짧은 ping 메시지로 모델 응답 1 token 유도 ("[cn:keepalive] reply 'ok' only.")
- timestamp 비교 메커니즘으로 multiple fire 중 가장 최근 것만 wake (사용자가 매 turn 마다 input 시 누적 sleep 방지). sleep 자체가 throttle 이라 wake-after-wake loop 도 자연 처리 (별도 무한 루프 차단 불필요)
- `cn install` / `cn uninstall` CLI (plugin 미사용 환경 fallback)
- `cn:status` 명령: 현재 mode + 마지막 wake 시각 + 다음 wake 예상 시각 + cache 추정 만료 시각 + 누적 wake 횟수 (vs max_refresh_count)
- **Config 옵션 (v0.2.x 호환 유지)**:
  - `general.mode` ∈ {`notify`, `auto`, `hybrid`} — default `hybrid` (기존 동일)
  - `general.refresh_interval_minutes` — default 50 (1h cache TTL 만료 직전, v0.2.x 기본값 55 → 50 으로 변경: POC C 30분 검증 + 안전 마진)
  - `general.max_refresh_count` — default 10. 자리비움 무한 wake 방지 (한 세션 누적 wake 상한). 사용자 input 시 reset
  - `notify.system_notification` — default true. macOS osascript 알림
  - `refresh.hybrid_wait_seconds` — default 60. `mode = hybrid` 의 알림 후 사용자 input 대기 시간

### 5.2 Out of scope

- Wake 메시지 (`refresh.prompt`) customization — 기본 prompt ("[cn:keepalive] reply 'ok' only.") 로 충분, 사용자 요청 발생 시 v0.4.0 검토
- Cache hit/miss metrics aggregation 또는 dashboard — 단일 책임 원칙 (cache TTL 갱신만)
- Multiple Stop hooks 충돌 감지 (사용자가 직접 settings 에 hook 추가 + plugin 동시 설치 시 중복 발화) — README 에 명시
- Mid-sleep user input 의 정교한 처리 (timestamp 비교로 충분, 추가 처리 불필요)
- 폐기되는 v0.2.x config 옵션:
  - `notify.terminal_bell` — hook 은 background 라 stdout 무관, system_notification 으로 대체
  - `notify.imminent_threshold_minutes` — sleep duration 자체가 cache TTL 만료 직전이라 의미 사라짐
  - `refresh.fire_timeout_seconds` — subprocess fire 폐기로 의미 사라짐 (hook 자체의 timeout 으로 대체)
  - `advanced.*` 모든 옵션 (daemon_*, fire_*, backoff_*, lock_* 등) — daemon 폐기로 의미 사라짐

### 5.3 폐기 (v0.2.x → v0.3.0)

- `daemon/` 디렉토리 전체 (subprocess fire, lock, idle shutdown, fire_timeout 로직)
- `~/.cache-necromancer/lock` + `state/` (런타임 상태 디렉토리). 단 `~/.cache-necromancer/marker/` (timestamp + count) 은 신규 사용
- PR #11 의 16개 회귀 가드 (subprocess fire 의미 사라짐)
- config 옵션: §5.2 의 "폐기되는 v0.2.x config 옵션" 항목 참조
- `/cn:dry-run` 명령 (subprocess fire preview 용 — 의미 사라짐)

## 6. Migration

### 6.1 기존 사용자 (v0.2.x)

업그레이드 시:
1. `pkill -f "python.*-m daemon" || true` — 기존 daemon 종료 시도 (이미 정지 상태면 무시)
2. `rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state` — stale 상태 정리 (디렉토리 없으면 무시)
3. `/plugin update cache-necromancer` (이미 설치된 경우) 또는 `/plugin install cache-necromancer` (신규)
4. (중요) 기존 chat 세션 재시작 — settings hot-reload 안 되므로 plugin 의 새 hook 등록은 새 세션부터 적용. `claude -c` 로 resume 가능하나 첫 wake 가 cache rebuild 비용 ($1+) 발생 가능

**Config 마이그레이션** — `~/.cache-necromancer/config.toml` 자동 처리:
- 호환 옵션 (`mode`, `refresh_interval_minutes`, `max_refresh_count`, `notify.system_notification`, `refresh.hybrid_wait_seconds`) — 그대로 유지
- 폐기 옵션 (`terminal_bell`, `imminent_threshold_minutes`, `fire_timeout_seconds`, `[advanced]` 전체) — `cn install` 이 detect 후 stdout 으로 "deprecated, ignored" 경고. config 파일은 사용자가 수동 cleanup
- 신규 default 변경: `refresh_interval_minutes` 55 → 50

CHANGELOG + README 의 Migration 섹션에 단계별 안내.

### 6.2 신규 사용자

1. `/plugin marketplace add github.com/token-keeper/cache-necromancer`
2. `/plugin install cache-necromancer`
3. 끝 — 추가 설정 없음

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Claude Code 가 1h cache 미사용 (5min default) | Low | POC C 30분 sleep 검증 완료 (cr 100% hit). 단 모델·정책 변경 시 재검증 필요 |
| Wake turn 에 모델이 tool/analysis 수행 (prompt 무시) → 비용 폭증 | Mid | POC 진단 시 cc=2,646 turn 에 Write+Bash 발생 사례 있음. Mitigation: prompt 명시 강화 ("Reply only 'ok'. No tools, no analysis. Do not look at conversation history."). 도구 자체가 monitoring 추가는 X (단일 책임 원칙) |
| settings hot-reload 안 됨 → 첫 활성화 시 cache 만료된 sessions 는 첫 wake 가 rebuild 비용 | Mid | README 에 명시 + `cn install` CLI 가 stdout 으로 "claude -c 또는 새 세션 필요" 경고 + `cn:status` 가 첫 hook fire 전에는 "settings 적용 대기 중" 표시 |
| Multiple Stop hooks 등록 시 중복 발화 | Low | `cn install` 이 settings 에 이미 hook 있으면 경고. README 에 명시 |
| Plugin install UX 의 Claude Code 버전 의존성 | Low | 최소 지원 버전 명시. fallback 으로 `cn install` CLI 제공 |
| Wake 메시지의 transcript noise (영구 기록) | Mid | 짧은 ping 메시지 ("ok" 응답) + Claude Code UI 가 reminder body hide 함을 확인 |
| `mode = notify` 사용자가 cache 갱신 효과 0 (cache rebuild 비용 그대로) | Low | README 에 "notify mode 는 알림만, 비용 절감 효과 없음" 명시. cn:status 에 현재 mode 표시 |

## 8. 도구 정신 (변경 없음)

- 민감정보 미기록: log 는 sid_hash + token 수만
- 단일 책임: cache TTL 갱신만
- 알파 단계: 비용 발생 (자동 모드)
- 이름 유지: alpha 배포 인지도 (rename 비용 큼). README 에 "previously fire-based, now asyncRewake-based" 명시

## 9. References

- [TECH_SPEC](2026-05-15-cache-necromancer-v0.3.0-TECH_SPEC.md)
- [PLAN](../plans/2026-05-15-cache-necromancer-v0.3.0-PLAN.md)
- [진단 doc — v0.2.2 cache investigation](../../handoff/2026-05-15-v0.2.2-cache-investigation.md) (Test 1~8 evidence)
- [진단 doc — v0.3.0 asyncRewake fix](../../handoff/2026-05-15-v0.3.0-asyncrewake-fix.md)
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Code hooks docs (asyncRewake field)](https://code.claude.com/docs/en/hooks.md)
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins.md)

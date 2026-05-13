# cache-necromancer

> **Claude Code 의 1시간 프롬프트 캐시 TTL이 만료되기 직전에 자동으로 캐시를 살리는 플러그인.** 죽어가는 캐시를 부활시키는 네크로맨서.

![status](https://img.shields.io/badge/status-alpha-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![platform](https://img.shields.io/badge/platform-macOS-lightgrey)

---

## 무엇이 문제인가

Claude Code 는 컨텍스트 캐시를 1시간 동안 보관한다. 그 안에 다음 요청을 보내면 캐시 read 비용 (정상의 약 10%) 만 청구되지만, 1시간이 지나면 만료되어 다음 요청은 전체 cache_create 비용을 다시 낸다.

**현실 시나리오**: 회의 / 점심 / 잠시 자리 비움 → 55분 경과 → 다시 작업하려 했더니 캐시 만료. 비용 ×10.

## 무엇을 하는가

`cache-necromancer` 는 마지막 응답 (Stop hook) 으로부터 55분이 지나기 직전, 유저가 작업 중이 아니면 최소 프롬프트 (`.`) 를 헤드레스로 보내 캐시 TTL 을 리셋한다.

핵심 명령어 (실제 호출):
```
claude -p "." --resume <session_id> --fork-session --no-session-persistence --output-format json
```

- `--fork-session`: 원본 transcript JSONL 무변경 (인터랙티브 세션 영향 0)
- `--no-session-persistence`: claude CLI 종료 시 fork transcript 정리
- `--output-format json`: usage 정확 파싱 (cache_read 확인)

실험적으로 확인된 결과: `cache_read=46,115 tokens` 발생 — 다음 사용자 turn 이 hot cache 활용.

## 설치

```bash
# 마켓플레이스 (출시 후)
/plugin install cache-necromancer

# 로컬 marketplace (현재)
/plugin marketplace add /path/to/cache-necromancer
/plugin install cache-necromancer@cache-necromancer-marketplace
```

설치 중 `mode` 프롬프트가 나오면 처음엔 **`notify`** 권장 (실제 fire 없이 알림만으로 동작 확인). 설치 후 `/reload-plugins` 한 번 + 짧은 응답 한 번 받으면 데몬이 spawn 되고 `~/.cache-necromancer/config.toml` 이 자동 생성됨.

## 작동 모드

`~/.cache-necromancer/config.toml` 에서 선택:

| mode | 동작 |
|------|------|
| `notify` | 캐시 만료 시점 도달 시 macOS 알림만. 실제 fire 안 함. |
| `auto` | 시점 도달 시 자동으로 헤드레스 fire. 사용자 개입 0. |
| `hybrid` (기본) | 시점 도달 시 60초 사전 알림 → 그 사이 사용자 입력 없으면 fire, 있으면 취소. |

```toml
[general]
mode = "hybrid"
refresh_interval_minutes = 55
max_refresh_count = 10              # 세션당 최대 자동 fire 횟수

[refresh]
prompt = "."
hybrid_wait_seconds = 60
fire_timeout_seconds = 120

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = 5
```

## 빠른 시작

설치 직후 다음 두 명령으로 충분:

```
/cn:config    # 현재 모드 + 변경 방법 확인
/cn:status    # 추적 세션 + 데몬 상태
```

기본 모드는 `hybrid` (사전 알림 → 60초 후 fire). 처음엔 `notify` (알림만) 로 안전하게 시작 권장:

```bash
mkdir -p ~/.cache-necromancer
echo '[general]
mode = "notify"' > ~/.cache-necromancer/config.toml
```

## 슬래시 명령

### `/cn:config`
현재 설정 + 3가지 모드 비교 + 변경 방법. 첫 사용자 권장 시작점.

### `/cn:status`
데몬 / 세션 / 다음 fire 시뮬레이션 / 24h fire 통계를 한 화면에 표시 (v0.2.0 — `/cn:dry-run` 흡수).

```
cache-necromancer 상태
────────────────────────────────
■ 데몬
  살아있음 (PID 12345, started 2026-05-13T10:00:00+00:00)

■ 세션 (active 2, disabled 0)
  [abc12345] (this)  next 25m 12s · refresh 3/10 · idle
  [def67890]         next 42m 03s · refresh 1/10 · in turn

■ 다음 fire 시뮬레이션 (active 세션)
  [abc12345]
      command:   claude -p . --resume '<sid:abc12345>' --fork-session --no-session-persistence --output-format json
      cwd:       /Users/me/projects/my-app
      last_fire: 2026-05-13T09:25:00+00:00 (ok)
  [def67890]
      command:   claude -p . --resume '<sid:def67890>' --fork-session --no-session-persistence --output-format json
      cwd:       /Users/me/projects/other

■ 최근 24h fires
  총 8회 (cache_cold=1, ok=7)

모드: 💀 hybrid — 60s 사전 알림 후 입력 없으면 fire (취소 가능) · max_refresh: 10
설정 변경 / 모드 비교: /cn:config
```

## 추천 사용 패턴

| 시나리오 | 추천 모드 |
|---------|----------|
| 자리 자주 비우는 / 회의 잦은 환경 | `auto` |
| 컨트롤 보존하면서 비용 절감 | `hybrid` (기본) |
| 처음 도입 / 동작 확인 | `notify` (실제 호출 없음, 알림만) |
| 무거운 hybrid 여러 세션 동시 | `auto` 권장 (hybrid 는 wait 동안 daemon poll loop 블로킹) |

## 비추천 / 주의

- **공식 권장 패턴 아님**: Anthropic 캐시 정책의 의도된 사용 방식이 아닐 수 있음 (회색지대). 개인 사용 목적.
- **자동 fire 비용**: 매 fire 마다 minimal turn 분 비용 (cache_read + 입력 6 토큰 + 출력 1-2 토큰). 손익은 "fire 비용 < hot cache 활용 turn 이 한 번이라도 발생" 일 때.
- **CACHE_COLD 가 반복되는 환경**: 2회 누적되면 영구 disabled. `/cn:status` 로 확인.
- **AUTH_ERROR**: 즉시 영구 disabled. `disabled_reason` 으로 원인 파악 후 `~/.cache-necromancer/state/<sid>.json` 삭제하면 다시 추적.

## 안전성 보장

- **원본 transcript JSONL 무변경** — `--fork-session` 덕분에 인터랙티브 세션은 영향 0
- **fork transcript 자동 정리** — `--no-session-persistence` 로 claude CLI 종료 시 처리 (cache-necromancer 가 직접 cleanup 안 함)
- **Hook 은 절대 Claude Code 를 깨뜨리지 않음** — 모든 hook 은 silent fail (exit 0)
- **민감정보 미기록** — 모든 log 는 `sid_hash` + token 수만. 프롬프트/응답 본문/cwd 절대 기록 안 함. 7일 후 자동 회전 삭제.
- **State 파일 권한 0600 / dir 0700** — 다른 사용자 접근 차단
- **데몬 단일 인스턴스 보장** — lockfile + PID/start_time 검증으로 중복 spawn 방지
- **OS sleep/wake 보정** — monotonic clock drift 감지 시 next_refresh_at 자동 미룸 (5분)

## 트러블슈팅

### 데몬이 안 뜬다
```bash
# 다음 Stop hook 에서 spawn 되는 lazy 패턴. 한 번 무엇이든 응답해보면 살아남.
/cn:status   # ■ 데몬 섹션에 "종료됨 — 다음 Stop hook 이 spawn" 표시
```

### 다른 프로젝트 세션이 자동 추적된다

설치 후 자기 작업 외 프로젝트 (`vdit-ios-sdk`, `other-app` 등) 의 세션이 `/cn:status` 에 자동 등장하는 건 의도된 동작이다. cache-necromancer 는 Stop hook 이 발화한 **모든** Claude Code 세션을 추적 대상으로 잡는다.

**비용 인지**: 추적 세션 수가 N 개면, `mode=auto/hybrid` 에서 세션당 `max_refresh_count` 만큼 fire 가 발생할 수 있다. 비용은 세션 수에 비례.

**정리 방법**:
```bash
# 1. 데몬 강제 종료 (다음 Stop hook 까지 재spawn 안 됨)
pkill -f "python.*cache.necromancer.*daemon"

# 2. 추적 중인 모든 세션 상태 삭제
rm -rf ~/.cache-necromancer/state/

# 3. (선택) 특정 세션만 정리 — sid_hash 는 /cn:status 출력의 [...] 안 prefix
rm ~/.cache-necromancer/state/<sid_hash>.json
```

또는 플러그인 자체 비활성화:
```
/plugin disable cache-necromancer
```

### 자동 fire 가 동작 안 함
1. `mode` 가 `notify` 인지 확인 → 알림만 받음
2. `disabled` 세션은 자동 fire 안 함 → `/cn:status` 에서 reason 확인
3. `backoff_until` 이 미래면 그 시점까지 대기

### 캐시가 만료된 채로 fire 됐다 (CACHE_COLD)
- 1회는 일시적 가능성 (스키마/timing) 으로 backoff 후 retry
- 2회 누적 → 영구 disabled (구조적 cold)

### 알림이 안 옴
- macOS 시스템 환경설정 → 알림 → Terminal/iTerm/Script Editor 권한 확인
- `[notify]` 섹션의 `system_notification = true` 확인

### 로그 위치
```
~/.cache-necromancer/
├── daemon.log.YYYY-MM-DD       # 데몬 일반 로그
├── fire.log.YYYY-MM-DD          # 모든 fire 결과 (Phase 4 대시보드용)
├── user_turn.log.YYYY-MM-DD     # 사용자 turn usage (after_fire 판정 포함)
├── daemon.lock                  # 단일 인스턴스 락
└── state/<sid_hash>.json        # 세션별 state
```

## 아키텍처 요약

```
Claude Code → Stop hook → on_stop.py → state 갱신 + 데몬 lazy spawn
                                            ↓
                              ┌──────────────────────────────┐
                              │  daemon (단일 인스턴스)        │
                              │  - poller: 동적 sleep + drift │
                              │  - watchdog: fire→Stop 복구   │
                              │  - scheduler: mode 분기       │
                              │  - refresh: claude -p 호출    │
                              │  - handler: 결과 후처리        │
                              └──────────────────────────────┘
                                            ↓
                              헤드레스 fire (cache TTL 리셋)
```

## 개발

```bash
# 의존성 설치 (uv 사용)
uv venv && uv sync --extra dev

# 테스트
.venv/bin/python -m pytest

# 통합 테스트 (실제 claude CLI 호출)
CN_INTEGRATION_SESSION_ID=<your-session-id> .venv/bin/python -m pytest tests/daemon/test_refresh_integration.py
```

## 라이선스

MIT — `LICENSE` 참조.

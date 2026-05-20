# cache-necromancer

> **Claude Code 의 1시간 프롬프트 캐시 TTL이 만료되기 직전에 자동으로 캐시를 살리는 플러그인.** 죽어가는 캐시를 부활시키는 네크로맨서.

![status](https://img.shields.io/badge/status-alpha-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![platform](https://img.shields.io/badge/platform-macOS-lightgrey)

---

## 무엇이 문제인가

Claude Code 는 컨텍스트 캐시를 1시간 동안 보관한다. 그 안에 다음 요청을 보내면 캐시 read 비용 (정상의 약 10%) 만 청구되지만, 1시간이 지나면 만료되어 다음 요청은 전체 `cache_create` 비용을 다시 낸다.

**현실 시나리오**: 회의 / 점심 / 잠시 자리 비움 → 50분 경과 → 다시 작업하려 했더니 캐시 만료 → 비용 ×10.

## 어떻게 동작하는가

매 user turn 끝마다 Claude Code 의 native **`Stop` hook + `asyncRewake`** 로 background sleep 을 걸어두고, 50분이 지나도 사용자 input 이 없으면 **chat 세션 자체가 자기 자신을 wake** 한다 (짧은 ping turn → 모델 `ok` 1 token).

핵심: chat 프로세스 안에서 turn 발사 → system prompt + tools byte-exact 보존 → **cache prefix 100% hit**. wake-up turn 평균 비용 ≤ $0.10 (Opus 1M ctx).

검증 결과:
- 30분 sleep 후 wake → cache 100% hit, $0.044
- 1M context 두 번째 wake → $0.085 (정상 `cache_create` 대비 94% 절감)

## 설치

```bash
/plugin marketplace add token-keeper/plugins
/plugin install cache-necromancer@token-keeper
```

설치 중 `mode` 프롬프트는 처음엔 **`hybrid`** 권장 (사전 알림 + 60초 후 자동 wake, 사용자 input 시 취소).

> Claude Code 는 settings hot-reload 안 함 — 설치 후 **새 chat 세션** 부터 hook 적용. `claude -c` 로 resume 가능하나 첫 wake 가 cache rebuild 비용 ($1+) 발생 가능.

## 작동 모드

`~/.cache-necromancer/config.toml` 에서 선택 (첫 hook fire 시 자동 생성):

| mode | 동작 |
|------|------|
| `notify` | 50분 후 macOS 알림만. wake X (cache 갱신 효과 0). |
| `auto` | 50분 후 자동 wake. 사용자 개입 0. |
| `hybrid` (기본) | 50분 후 알림 → 60초 동안 user input 없으면 wake, 있으면 취소. |

```toml
[general]
mode = "hybrid"
refresh_interval_minutes = 50         # cache TTL 만료 직전 (1h cache 기준)
max_refresh_count = 10                # 한 세션 최대 wake/notify 횟수

[notify]
system_notification = true            # macOS osascript 알림

[refresh]
hybrid_wait_seconds = 60              # hybrid 모드 알림 후 사용자 input 대기
```

## 슬래시 명령

| 명령 | 설명 |
|---|---|
| `/cn:config` | 현재 모드 + 3 모드 비교 + 변경 방법 |
| `/cn:status` | 현재 세션 + 다른 세션 + 다음 발동 예상 (API 비용 0 — `UserPromptExpansion` hook 기반) |

### `/cn:status` 출력 예시

```
┌─ 🔮 cache-necromancer 상태 ─────────────────────────────────────────────┐
│ mode: 💀 hybrid — sleep 후 알림 → 60s 동안 입력 없으면 wake (취소 가능) │
│ refresh_interval: 50m · max_refresh: 10                                 │
│                                                                         │
│ ┌─ 세션 (현재) ──────────────────────────────────┐                      │
│ │ sid:             a1b2c3...****                 │                      │
│ │ repeat count:    3 / 10                        │                      │
│ │ 다음 발동 예상:  2026-05-21 12:20:00 (5m 후)   │                      │
│ └────────────────────────────────────────────────┘                      │
│                                                                         │
│ ┌─ 다른 세션 ─────────────────────┐                                     │
│ │ ┌─ d4e5f6 ──────────────────┐   │                                     │
│ │ │ 다음:    12:18:30 (3m)    │   │                                     │
│ │ │ 마지막:  "코딜리티 Q3..." │   │                                     │
│ │ └───────────────────────────┘   │                                     │
│ └─────────────────────────────────┘                                     │
│                                                                         │
│ ┌─ 설정 상태 ──────────────────────────────────────┐                    │
│ │ plugin: cache-necromancer v0.3.x (active)        │                    │
│ │ hook 등록: ✅ plugin manifest                    │                    │
│ │ deprecated config: 없음                          │                    │
│ └──────────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

Wake 가 발생하면 transcript 에 다음과 같이 남는다:

```
[cn:keepalive 16:42 KST, 3/10] reply with exactly 'ok @16:42 (3/10)'. ...
ok @16:42 (3/10)
```

시각 + repeat count 가 함께 찍히므로 scrollback 만 봐도 언제 몇 번째 wake 였는지 즉시 식별된다.

## 아키텍처 요약

```
┌────────────────────────────────────────────────────────────┐
│  Claude Code chat session (PID A)                          │
│                                                            │
│  user input → assistant turn → Stop event                  │
│       ▼                                                    │
│  hook (asyncRewake: true): refresh.py background 실행      │
│       ▼                                                    │
│  refresh.py:                                               │
│    1. marker.latest_fire = now (ns 단위, race-resistant)   │
│    2. wake_count >= max → exit 0                           │
│    3. sleep 50분 (cache TTL 직전)                          │
│    4. latest_fire 재확인 (newer fire → exit 0)             │
│    5. mode 분기:                                           │
│       - notify: osascript + exit 0                         │
│       - auto:   stderr ping + exit 2 (chat 자체 wake)      │
│       - hybrid: 알림 + 60s wait + 재확인 + exit 2          │
└────────────────────────────────────────────────────────────┘
```

핵심 원리: chat 프로세스 자체가 wake → system prompt + tools byte-exact 보존 → cache prefix 100% hit.

## 트러블슈팅

### 첫 wake 가 큰 비용 ($1+)
`claude -c` 로 resume 한 세션의 cache 가 이미 만료된 상태였으면 첫 wake 가 cache rebuild 발생. 정상 동작.

### settings 변경이 적용 안 됨
Claude Code 는 settings hot-reload 안 함. 새 chat 세션 시작 필요.

### wake 가 발생하지 않음
1. `mode = notify` → wake 안 함 (알림만)
2. `repeat count` 가 `max_refresh_count` 도달 → user input 으로 reset 됨
3. 사용자가 input 한 직후 50분 안에는 wake 안 함 (정상)
4. `/cn:status` 의 hook 등록 상태 확인
5. 마커가 안 생기면 hook 의 stdin payload 가 비어있을 가능성 — `refresh.py` 는 stdin JSON 의 `session_id` 우선, `CLAUDE_CODE_SESSION_ID` env 변수 fallback (둘 다 비어있으면 silent exit 0)
6. `config.toml` 이 없으면 첫 hook fire 가 default 로 자동 생성 (수동 작성 불필요)

### Wake 메시지가 transcript 에 노이즈
Wake-up turn (`<task-notification>` + ping + 모델 `ok` 응답) 은 영구 transcript 기록. UI 가 reminder body 는 hide 하지만 응답은 visible.

### 다른 프로젝트 세션이 자동 추적된다
모든 Claude Code 세션의 Stop hook 이 fire 됨. 의도된 동작. 비용은 세션 수에 비례.

```bash
# 정리: 특정 sid 의 marker 삭제
rm ~/.cache-necromancer/marker/<sid_hash>.json

# 또는 플러그인 비활성화
/plugin disable cache-necromancer
```

### 알림이 안 옴
- macOS 시스템 환경설정 → 알림 → Terminal/iTerm/Script Editor 권한 확인
- `[notify].system_notification = true` 확인

### 로그 위치
```
~/.cache-necromancer/
├── cn.log.YYYY-MM-DD       # refresh / on_user_prompt / on_session_end 로그 (sid_hash + token만)
├── config.toml             # 사용자 설정
└── marker/<sid_hash>.json  # 세션별 marker (latest_fire / wake_count / last_wake_at)
```

> v0.3.2 이전 사용자: 옛 `daemon.log.*` 파일은 자동 정리되지 않음. 필요 시 수동 삭제 (`rm ~/.cache-necromancer/daemon.log.*`).

## 안전성 보장

- **Silent fail**: 모든 hook 은 silent fail (exit 0). chat 동작 차단 X.
- **민감정보 미기록**: log 는 `sid_hash` + token 수만. 프롬프트/응답 본문 절대 기록 X. 7일 자동 회전.
- **권한**: marker file 0600 / dir 0700 — 다른 사용자 접근 차단.
- **Atomic write**: marker file 은 `tempfile + os.replace()` POSIX 원자성 보장.
- **Graceful degradation**: 저장 실패 시 wake 1회 포기, chat 영향 X.

## 비추천 / 주의

- **공식 권장 패턴 아님**: Anthropic 캐시 정책의 의도된 사용 방식이 아닐 수 있음 (회색지대). 개인 사용 목적.
- **자동 wake 비용**: 매 wake 마다 minimal turn (`cache_read` + 입력 수백 token + 출력 ~10 token). 손익은 "wake 비용 < hot cache 활용 turn 이 한 번이라도 발생" 일 때.
- **Wake 메시지의 transcript noise**: 영구 기록. wake-up assistant 응답 (`ok @HH:MM (N/M)`) visible.

## 개발

```bash
# 의존성 설치 (uv)
uv venv && uv sync --extra dev

# 테스트
uv run pytest      # 131 passed
```

## v0.2.x 에서 업그레이드

v0.3.0 부터 daemon-based 구조는 폐기되고 `asyncRewake` hook 으로 전환됐다.

```bash
# 1. v0.2.x daemon 정지
pkill -f "python.*-m daemon" || true

# 2. stale 파일 정리
rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state

# 3. 플러그인 업그레이드
/plugin update cache-necromancer

# 4. (중요) 새 chat 세션 시작 — Claude Code 는 settings hot-reload 안 함
```

기존 `config.toml` 의 호환 옵션은 그대로 동작하고, 폐기 옵션은 stderr 경고 후 무시된다. 자세한 변경은 `CHANGELOG.md` 참조.

## 변경 이력

`CHANGELOG.md` 참조. 최신: **v0.3.11** (2026-05-19) — `on_user_prompt` 의 wake_count reset 무한 루프 fix.

## 라이선스

MIT — `LICENSE` 참조.

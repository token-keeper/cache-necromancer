# cache-necromancer

> **Claude Code 의 1시간 프롬프트 캐시 TTL이 만료되기 직전에 자동으로 캐시를 살리는 플러그인.** 죽어가는 캐시를 부활시키는 네크로맨서.

![status](https://img.shields.io/badge/status-alpha-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![platform](https://img.shields.io/badge/platform-macOS-lightgrey)

> **v0.3.0**: 아키텍처 전면 전환. v0.2.x 의 외부 daemon + `claude -p` fire 가 cache namespace 분리 (chat 의 system prompt 와 `-p` 의 system prompt 가 byte 단위로 다름) 때문에 실제로는 cache TTL 갱신 못 하던 fundamental 결함을 발견. **Claude Code 의 native Stop hook + `asyncRewake`** 로 chat 세션이 자기 자신을 wake 하는 방식으로 전환 (system prompt + tools byte-exact 보존 → cache prefix 100% hit). [Migration 가이드](#migration-v02x--v030) 참조.

---

## 무엇이 문제인가

Claude Code 는 컨텍스트 캐시를 1시간 동안 보관한다. 그 안에 다음 요청을 보내면 캐시 read 비용 (정상의 약 10%) 만 청구되지만, 1시간이 지나면 만료되어 다음 요청은 전체 cache_create 비용을 다시 낸다.

**현실 시나리오**: 회의 / 점심 / 잠시 자리 비움 → 50분 경과 → 다시 작업하려 했더니 캐시 만료. 비용 ×10.

## 무엇을 하는가 (v0.3.0)

`cache-necromancer` 의 **Stop hook + asyncRewake** 가 매 user turn 끝마다 background 에서 50분 sleep → 사용자 input 없으면 chat 세션 자체를 wake (짧은 ping turn → 모델 응답 'ok' 1 token).

핵심 차이: chat 세션 프로세스 안에서 turn 발사 → system prompt + tools byte-exact 보존 → cache prefix 100% hit. wake-up turn 평균 비용 ≤ $0.10 (Opus 1M ctx).

검증 결과 (v0.3.0 진단):
- 30분 sleep 후 wake → cr=44.55K (cache 100% hit, $0.044)
- 1M context 두 번째 wake → cc=586 / cr=153,700 / $0.085 (94% 절감)

## 설치

```bash
# Marketplace (출시 후)
/plugin install cache-necromancer

# 로컬 marketplace (현재)
/plugin marketplace add /path/to/cache-necromancer
/plugin install cache-necromancer@cache-necromancer-marketplace
```

설치 중 `mode` 프롬프트는 처음엔 **`hybrid`** 권장 (사전 알림 + 60초 후 자동 wake, 사용자 input 시 취소).

> **중요**: Claude Code 는 settings hot-reload 안 함 — 설치 후 **새 chat 세션** 부터 hook 적용. `claude -c` 로 resume 가능하나 첫 wake 가 cache rebuild 비용 ($1+) 발생 가능.

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

## 빠른 시작

```
/cn:config    # 현재 모드 + 변경 방법
/cn:status    # 현재 세션 + 다른 세션 + 다음 발동 예상
```

## 슬래시 명령

### `/cn:config`
현재 설정 + 3 모드 비교 + 변경 방법.

### `/cn:status`
현재 세션 + 다른 세션 + 설정 상태를 한 화면에 표시. **`UserPromptExpansion` hook 기반 LLM turn 0회** (API 비용 0 — cache 절약 도구 정체성과 일관).

```
┌─ 🔮 cache-necromancer 상태 ─────────────────────────────────────────────┐
│ mode: 💀 hybrid — sleep 후 알림 → 60s 동안 입력 없으면 wake (취소 가능) │
│ refresh_interval: 50m · max_refresh: 10                                 │
│                                                                         │
│ ┌─ 세션 (현재) ──────────────────────────────────┐                      │
│ │ sid:             a1b2c3...****                 │                      │
│ │ repeat count:    3 / 10                        │                      │
│ │ 다음 발동 예상:  2026-05-16 12:20:00 (5m 후)   │                      │
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

## Migration (v0.2.x → v0.3.0)

v0.2.x daemon-based architecture 가 v0.3.0 asyncRewake hook architecture 로 전환됨. 다음 단계:

```bash
# 1. v0.2.x daemon 정지 (이미 정지면 무시)
pkill -f "python.*-m daemon" || true

# 2. v0.2.x stale 파일 정리
rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state

# 3. 플러그인 업그레이드 (이미 설치됨)
/plugin update cache-necromancer
# 또는 신규
/plugin install cache-necromancer

# 4. (중요) 기존 chat 세션 재시작 — Claude Code 는 settings hot-reload 안 함
```

### Config 마이그레이션

기존 `~/.cache-necromancer/config.toml` 의 호환 옵션은 그대로 동작:
- `general.mode`, `general.refresh_interval_minutes`, `general.max_refresh_count`
- `notify.system_notification`
- `refresh.hybrid_wait_seconds`

폐기된 옵션 (detect 시 stderr 경고 + 무시):
- `notify.terminal_bell`, `notify.imminent_threshold_minutes`
- `refresh.prompt`, `refresh.fire_timeout_seconds`
- `[advanced]` 전체 (12 필드)

`refresh_interval_minutes` 의 default 가 55 → 50 으로 변경. 기존에 명시적으로 set 한 값은 그대로 유지.

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
5. 마커가 안 생기면 hook 의 stdin payload 가 비어있을 가능성 — refresh.py 는 stdin JSON 의 `session_id` 우선, `CLAUDE_CODE_SESSION_ID` env 변수 fallback (둘 다 비어있으면 silent exit 0)
6. `config.toml` 이 없으면 첫 hook fire 가 default 로 자동 생성 (수동 작성 불필요)

### Wake 메시지가 transcript 에 노이즈
Wake-up turn (`<task-notification>` + ping + 모델 'ok' 응답) 은 영구 transcript 기록. UI 가 reminder body 는 hide 하지만 'ok' 응답은 visible.

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
├── cn.log.YYYY-MM-DD           # refresh.py / on_user_prompt / on_session_end 로그 (sid_hash + token만)
├── config.toml                 # 사용자 설정
└── marker/<sid_hash>.json      # 세션별 marker (latest_fire / wake_count / last_wake_at)
```

> **v0.3.2 이전 사용자**: 옛 `daemon.log.*` 파일은 자동 정리되지 않음. 필요 시 수동 삭제: `rm ~/.cache-necromancer/daemon.log.*`

## 아키텍처 요약 (v0.3.0)

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

핵심 원리: chat 프로세스 (PID A) 자체가 wake. system prompt + tools byte-exact 보존 → cache prefix 100% hit.

## 안전성 보장

- **PRD 불변**: 모든 hook 은 silent fail (exit 0). chat 동작 차단 X.
- **민감정보 미기록**: log 는 `sid_hash` + token 수만. 프롬프트/응답 본문 절대 기록 X. 7일 자동 회전.
- **Marker file 권한 0600 / dir 0700** — 다른 사용자 접근 차단.
- **Atomic write**: marker file 은 `tempfile + os.replace()` POSIX 원자성 보장.
- **Graceful degradation**: 저장 실패 시 wake 1회 포기, chat 영향 X.

## 비추천 / 주의

- **공식 권장 패턴 아님**: Anthropic 캐시 정책의 의도된 사용 방식이 아닐 수 있음 (회색지대). 개인 사용 목적.
- **자동 wake 비용**: 매 wake 마다 minimal turn (`cache_read` + 입력 수백 token + 출력 1-2 token). 손익은 "wake 비용 < hot cache 활용 turn 이 한 번이라도 발생" 일 때.
- **Wake 메시지의 transcript noise**: 영구 기록. wake-up assistant 응답 ('ok') visible.

## 개발

```bash
# 의존성 설치 (uv 사용)
uv venv && uv sync --extra dev

# 테스트
.venv/bin/python -m pytest

# CLI 로컬 테스트
.venv/bin/pip install -e .
cn --help
```

## 라이선스

MIT — `LICENSE` 참조.

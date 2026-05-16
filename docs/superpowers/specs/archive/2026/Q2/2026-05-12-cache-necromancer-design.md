# cache-necromancer 설계

작성일: 2026-05-12
상태: 설계 (구현 전)

## 개요

Claude Code의 1시간 프롬프트 캐시 TTL을 자동으로 갱신해서 캐시 비용 절감 효과를 유지하는 Claude Code 플러그인. 마지막 응답 후 55분이 지나기 직전, 사용자가 작업 중이 아니면 최소 프롬프트(`.`)를 tmux에 자동 주입해 캐시 수명을 1시간 연장한다.

개인 사용 목적. Anthropic 공식 권장 사용 패턴은 아님(회색지대).

## 결정 요약

| 항목 | 결정 |
|------|------|
| 구현 언어 | Python |
| MVP 범위 | notify / auto / hybrid 3개 모드 모두 |
| `max_refresh_count` 기본값 | 10 (≈10시간) |
| tmux 외부 실행 | 무시 (`$TMUX` 없으면 비활성) |
| 세션 ID | hook JSON의 `session_id` 필드 |
| 배포 형태 | Claude Code 플러그인 (`.claude-plugin/plugin.json`) |
| 데몬 실행 | Hook 레이지 기동 (lockfile 기반) |
| 알림 채널 | macOS 시스템 알림 + 터미널 벨 |
| 데몬 종료 | 모든 세션 1시간 stale 시 자체 종료 |
| 부수 채널 | notify / fire (send-keys) / log 3종 |

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code 인스턴스 (tmux pane마다 1개)               │
│                                                         │
│  UserPromptSubmit hook → state/{sid}.json 업데이트      │
│                          last_user_input_at = now       │
│                                                         │
│  Stop hook             → state/{sid}.json 업데이트      │
│                          last_stop_at = now             │
│                          next_refresh_at = now + 55min  │
│                          tmux_target = "sess:win.pane"  │
│                       → 데몬 살아있는지 체크, 없으면 spawn │
│                                                         │
│  SessionEnd hook       → state/{sid}.json 삭제          │
└─────────────────────────────────────────────────────────┘
                          ↓
        ~/.cache-necromancer/state/{session_id}.json
                          ↓
┌─────────────────────────────────────────────────────────┐
│  cache-necromancer 데몬 (lazy, lockfile 기반 단일 인스턴스)│
│                                                         │
│  30초 폴링:                                             │
│    for each state file:                                 │
│      if last_stop_at > last_user_input_at              │
│         and now >= next_refresh_at                     │
│         and refresh_count < max:                       │
│        execute_mode(session)                           │
│                                                         │
│  fire: `tmux send-keys -t {target} "." Enter`          │
│  notify: osascript 알림 + 터미널 벨                     │
│  log: ~/.cache-necromancer/daemon.log                  │
│                                                         │
│  모든 세션 1시간 무활동 → 데몬 자체 종료                │
└─────────────────────────────────────────────────────────┘
```

## 컴포넌트 구조

```
cache-necromancer/
├── .claude-plugin/
│   └── plugin.json              # 매니페스트 (hook 등록)
├── hooks/
│   ├── on_stop.py               # Stop hook 엔트리
│   ├── on_user_prompt.py        # UserPromptSubmit hook 엔트리
│   └── on_session_end.py        # SessionEnd hook (state 파일 정리)
├── daemon/
│   ├── __main__.py              # `python -m daemon` 진입점
│   ├── poller.py                # 30초 폴링 루프
│   ├── refresh.py               # tmux send-keys 실행
│   └── notifier.py              # macOS 알림 + 터미널 벨
├── lib/
│   ├── state.py                 # 세션 JSON 읽기/쓰기 (락 포함)
│   ├── config.py                # config.toml 로드
│   ├── lockfile.py              # 데몬 PID/lockfile 관리
│   └── logger.py                # daemon.log 기록
├── tests/
│   └── ...
├── config.toml.example          # 설정 예시
└── README.md
```

**책임 분리**
- `hooks/*`: Claude Code 진입점. timestamp 기록 후 즉시 종료. 데몬 미기동 시 백그라운드 spawn.
- `daemon/*`: 폴링 + 판정 + 사이드 이펙트 실행.
- `lib/*`: 순수 함수 위주. 테스트 용이.

## 상태 모델

저장 위치: `~/.cache-necromancer/state/{session_id}.json`

```json
{
  "session_id": "abc123",
  "cwd": "/Users/brody/projects/vdit",
  "tmux_target": "main:0.1",
  "last_stop_at": "2026-05-12T14:30:00+09:00",
  "last_user_input_at": "2026-05-12T14:25:00+09:00",
  "refresh_count": 0,
  "next_refresh_at": "2026-05-12T15:25:00+09:00",
  "imminent_notified": false,
  "created_at": "2026-05-12T13:00:00+09:00"
}
```

`next_refresh_at`은 fire 직후 `null`로 비워지며, 다음 Stop hook이 다시 값을 채울 때까지 갱신 판정 대상에서 제외된다. `imminent_notified`는 임박 알림 중복 방지 플래그로, `next_refresh_at`이 새로 설정될 때 함께 `false`로 리셋된다.

**갱신 판정 조건 (전부 AND)**
1. `last_stop_at > last_user_input_at` — 사용자 작업 중 아님
2. `now >= next_refresh_at` — 55분 도달
3. `refresh_count < max_refresh_count` — 한도 미달
4. `tmux_target is not None` — tmux 환경에서 생성됨

**파일 락**: Python `fcntl.flock`. Hook과 데몬 동시 접근 안전.

**세션 정리**
- 정상: SessionEnd hook이 해당 state 파일 삭제.
- 비정상(Claude Code 강제 종료 등): 데몬이 24시간 stale 파일 자동 GC.

## 설정 파일

위치: `~/.cache-necromancer/config.toml`

```toml
[general]
mode = "hybrid"                  # notify | auto | hybrid
refresh_interval_minutes = 55
max_refresh_count = 10           # -1 = 무제한

[refresh]
prompt = "."
hybrid_wait_seconds = 60         # hybrid 모드 알림→fire 대기 시간

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = 5   # 갱신 N분 전 임박 알림

[advanced]
daemon_poll_interval = 30
session_ttl_hours = 24           # stale GC 기준
daemon_idle_shutdown_minutes = 60 # 모든 세션 무활동 시 데몬 종료
```

## 데이터 흐름

### 1. Stop hook 호출

```
입력 JSON (stdin):
  { "session_id", "transcript_path", "cwd", "hook_event_name": "Stop" }

처리:
  1. state/{sid}.json 업데이트
       last_stop_at = now
       next_refresh_at = now + 55min
       imminent_notified = false  (다음 사이클 새로 알릴 수 있도록)
       tmux_target = tmux display-message -p "#S:#I.#P" (TMUX 있을 때)
  2. log 기록: "[stop] sid=abc123 next_refresh=15:25"
  3. lockfile 체크
       살아있으면: 아무것도 안 함
       없으면: subprocess.Popen(detached, "python -m daemon")
  4. exit 0 (stdout 비움)
```

### 2. UserPromptSubmit hook 호출

```
입력 JSON (stdin):
  { "session_id", "transcript_path", "cwd", "prompt", "hook_event_name": "UserPromptSubmit" }

처리:
  1. state/{sid}.json 업데이트
       last_user_input_at = now
       (next_refresh_at은 다음 Stop hook에서 재설정됨)
  2. log 기록: "[user] sid=abc123"
  3. exit 0
```

### 3. SessionEnd hook 호출

```
처리:
  1. state/{sid}.json 삭제
  2. log 기록: "[end] sid=abc123"
  3. exit 0
```

### 4. 데몬 폴링 루프 (30초마다)

```
for state_file in glob("state/*.json"):
    s = read_state(state_file)
    
    # next_refresh_at이 비어있으면 (fire 직후) 다음 Stop hook 대기
    if s.next_refresh_at is None:
        continue
    
    # 임박 알림 (1회만)
    if not s.imminent_notified and now >= s.next_refresh_at - 5min:
        notify(f"⏰ {s.session_id} 캐시 갱신 5분 전")
        s.imminent_notified = True
        save_state(s)
    
    # 갱신 시점
    if s.last_stop_at > s.last_user_input_at \
       and now >= s.next_refresh_at \
       and s.refresh_count < max_refresh_count:
        execute_mode(s)
        s.refresh_count += 1
        s.next_refresh_at = None   # 다음 Stop에서 재설정될 때까지 대기
        save_state(s)

# idle 셧다운
if all_sessions_stale_for(60min):
    exit 0
```

### 5. 모드별 실행 (execute_mode)

```
mode == "notify":
    notifier.notify("🔄 {sid} 캐시 갱신 시점 도달")
    log("[would-fire] sid=...")
    # fire 안 함

mode == "auto":
    refresh.fire(s.tmux_target, prompt=".")
    log("[fire] sid=... target=main:0.1")

mode == "hybrid":
    notifier.notify("🔄 {sid} 60초 내 입력 없으면 자동 갱신")
    time.sleep(60)
    # 다시 state 읽어서 last_user_input_at 변경됐는지 확인
    if state_unchanged(s):
        refresh.fire(s.tmux_target, prompt=".")
        log("[fire] sid=... (hybrid)")
    else:
        log("[cancel] sid=... user input during hybrid wait")
```

## 에러 처리

| 상황 | 처리 |
|------|------|
| tmux 외부에서 hook 호출 | `$TMUX` 없으면 state 파일 생성 안 함, silent exit 0 |
| state 파일 손상 | `json.JSONDecodeError` 시 `.corrupt`로 백업 후 제거, log 경고 |
| 데몬 spawn 실패 | hook에서 log만 남기고 exit 0. Claude Code 영향 없음 |
| 데몬 중복 기동 | lockfile + `fcntl.flock(LOCK_EX\|LOCK_NB)` 미획득 시 즉시 종료 |
| send-keys 실패 (pane 사라짐) | log 경고, state 파일 정리, 해당 세션 비활성화 |
| macOS 알림 권한 없음 | osascript 실패 캡처, log 경고, 터미널 벨로 fallback |
| 시계 역행 (NTP 보정) | `now < last_stop_at` 감지 시 `last_stop_at = now` 보정, log 경고 |
| Claude Code 강제 종료 | SessionEnd 미발사 → 24시간 GC가 정리 |

**원칙**: hook은 어떤 경우에도 Claude Code 동작에 영향 주지 않는다. 항상 `exit 0`, stdout 비움. 데몬 오류는 log에만 기록.

## 테스트 전략

### 단위 테스트
- `lib/state.py`: 파일 락, 동시 쓰기, 손상 복구, atomic write
- `lib/config.py`: TOML 파싱, 기본값, 누락 키 처리
- `daemon/poller.py`: 판정 로직 (freezegun으로 시간 mock)
- `daemon/refresh.py`: tmux send-keys 명령 생성 (subprocess mock)
- `daemon/notifier.py`: osascript 호출 (mock)

### 통합 테스트
- Hook 시뮬레이션: 가짜 JSON stdin → state 파일 변화 검증
- 데몬 단일 사이클: 가짜 state 파일 → 판정 결과 검증
- Hybrid 시퀀스: 알림 → 60초 대기 → 사용자 입력 발생 → 취소 검증

### 수동 검증 (README 기재)
1. `mode=notify`: 55분 대기 → macOS 알림 뜨는지
2. `mode=auto`: 55분 대기 → tmux pane에 `.` 자동 입력되는지
3. `mode=hybrid`: 알림 후 사용자 입력 → 갱신 취소되는지
4. 강제 종료 후 24시간 → state 파일 GC 확인

도구: pytest + freezegun(시간 mock) + 실제 tmux 호출

## plugin.json 매니페스트 (초안)

```json
{
  "name": "cache-necromancer",
  "version": "0.1.0",
  "description": "Auto-refresh Claude Code prompt cache TTL via minimal injection",
  "hooks": {
    "Stop": "hooks/on_stop.py",
    "UserPromptSubmit": "hooks/on_user_prompt.py",
    "SessionEnd": "hooks/on_session_end.py"
  },
  "requires": {
    "platform": ["darwin"],
    "tools": ["tmux", "python3"]
  }
}
```

(실제 plugin.json 스키마는 Anthropic 공식 문서 기준으로 구현 단계에서 확정)

## 빌드 단계

### Phase 1 (Hook + 데몬 골격 + notify 모드)
1. 디렉토리 구조, `plugin.json`, `config.toml.example`
2. `lib/state.py`, `lib/config.py`, `lib/lockfile.py`, `lib/logger.py`
3. 3개 hook 스크립트 (state 기록만)
4. `daemon/__main__.py` + `poller.py` (notify 모드만)
5. `daemon/notifier.py` (macOS 알림 + 벨)
6. 단위 테스트
7. 수동 시나리오 #1 통과

### Phase 2 (auto / hybrid 모드 + send-keys)
1. `daemon/refresh.py` (tmux send-keys)
2. `poller.py`에 auto/hybrid 분기 추가
3. 통합 테스트
4. 수동 시나리오 #2, #3 통과

## 비기능 요구사항

- Hook 실행 시간 < 100ms (Claude Code 응답성 영향 최소화)
- 데몬 메모리 < 50MB
- log 파일은 일자별 회전 (`daemon.log.YYYY-MM-DD`), 7일 후 자동 삭제
- 모든 timestamp는 ISO 8601 + 타임존(`+09:00`) 포함

## 미해결 / 추후 결정

- Phase 3 (통계/대시보드)는 별도 spec로 분리
- 다른 OS 지원(linux 알림)은 v1 이후
- Anthropic이 캐시 정책 변경 시 대응 매뉴얼 필요

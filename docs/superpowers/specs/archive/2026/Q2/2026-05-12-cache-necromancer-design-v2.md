# cache-necromancer 설계 v2

작성일: 2026-05-12 (v2 개정)
상태: 설계 (구현 전)
이전 버전: `2026-05-12-cache-necromancer-design.md`

**v2 개정 사유**: Codex 리뷰로 CRITICAL 3건 / MAJOR 5건 발견. 가장 큰 결함은 `plugin.json` 형식이 공식 스키마와 맞지 않아 플러그인 로드 자체가 불가능했다는 점.

## 개요

Claude Code의 1시간 프롬프트 캐시 TTL을 자동으로 갱신해서 캐시 비용 절감 효과를 유지하는 Claude Code 플러그인. 마지막 응답 후 55분이 지나기 직전, 사용자가 작업 중이 아니면 최소 프롬프트(`.`)를 tmux에 자동 주입해 캐시 수명을 1시간 연장한다.

**중요한 메커니즘 명세**: Stop hook 자체가 TTL을 갱신하는 게 아니다. Stop hook은 단순히 "마지막 응답 시각"을 기록할 뿐이며, **실제 TTL 갱신은 `tmux send-keys "." Enter` 결과로 새 Claude 요청이 발생해서 기존 캐시 prefix가 읽힐 때 일어난다**. 캐시 hit이 안 되면(예: 캐시가 이미 만료된 후 fire 발생) 갱신 효과 없이 새 캐시가 만들어진다. 데몬은 만료 전(55분)에 fire하므로 정상 동작 시 항상 갱신.

개인 사용 목적. Anthropic 공식 권장 사용 패턴 아님(회색지대).

## 결정 요약

| 항목 | 결정 |
|------|------|
| 구현 언어 | Python 3.11+ |
| MVP 범위 | notify / auto / hybrid 3개 모드 |
| `max_refresh_count` 기본값 | 10 (≈10시간) |
| tmux 외부 실행 | 무시 (`$TMUX` 없으면 비활성) |
| 세션 ID | hook JSON의 `session_id` 필드 (파일명 사용 시 sanitize) |
| 배포 형태 | Claude Code 플러그인 (`.claude-plugin/plugin.json` + `hooks/hooks.json`) |
| 데몬 실행 | Hook 레이지 기동 (lockfile + stale PID 처리) |
| 알림 채널 | macOS 시스템 알림 + 터미널 벨 |
| 데몬 종료 | 모든 세션 1시간 stale 시 자체 종료 |
| 채널 | notify / fire (send-keys) / log |
| 폴링 | 동적 sleep (`min(60, next_fire_in)`) |

## 코덱스 리뷰 반영 항목

### CRITICAL 3건

1. **plugin.json 공식 스키마 준수** → 아래 "플러그인 매니페스트" 섹션 재작성. `hooks/hooks.json` 분리, `platform/tools/requires` 필드 제거, `${CLAUDE_PLUGIN_ROOT}` 사용.
2. **tmux pane 상태 검증** → "fire 전 안전 검증" 섹션 신설. `tmux display-message`로 pane이 claude 프로세스 + 빈 버퍼인지 확인 후 주입.
3. **macOS sleep/wake 보정** → "타이머 보정" 섹션 신설. `time.monotonic()` 드리프트 감지 시 모든 세션의 `next_refresh_at`을 `now + 5분`으로 유예.

### MAJOR 5건

4. **fcntl.flock + atomic write** → read-modify-write 전체를 락 범위로, 쓰기는 `os.replace()` atomic rename.
5. **stale PID 처리** → `os.kill(pid, 0)` 체크, 죽었으면 락 강제 해제 후 재기동. 데몬 spawn 시 stdout/stderr → `/dev/null`, `setsid`로 새 세션 그룹.
6. **동적 sleep** → 폴링 루프에서 `sleep_seconds = max(1, min(60, next_fire_in_seconds))` 계산.
7. **Stop hook recursion 차단** → fire 시 환경변수 `CACHE_NECROMANCER_INJECTED=1`을 prompt 앞에 prefix할 수는 없으므로, **state 파일에 `last_fire_at` 기록 + Stop hook이 자기 fire 직후의 Stop인지 (`now - last_fire_at < 5초`) 판정해서 refresh_count 무한 증가 차단**.
8. **session_id sanitize** → 파일명에 사용 전 `re.match(r'^[a-zA-Z0-9_-]+$', sid)` 검증, 실패 시 `sha256(sid)[:16]` 사용.

### MINOR 4건

9. async timeout 기본값 600초 명시. `timeout: 5` 등 작은 값 권장.
10. "사용자 타이핑 중이지만 Enter 미입력" 상태 감지 불가 — 한계 명시. tmux pane buffer 비어있음 확인이 추가 safety.
11. MVP 과설계 — `auto` 단일 모드부터 검증, hybrid/notify는 Phase 2. 단, 사용자 결정으로 v2는 3개 모드 모두 유지.
12. 24h GC는 너무 늦음 — `pane_pid` liveness check를 poll loop에 추가, pane 죽음 즉시 비활성화.

## 아키텍처 (수정)

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code 인스턴스 (tmux pane마다 1개)               │
│                                                         │
│  hooks/hooks.json 등록:                                 │
│    UserPromptSubmit → on_user_prompt.py                 │
│    Stop             → on_stop.py                        │
│    SessionEnd       → on_session_end.py                 │
│                                                         │
│  hook 호출 흐름:                                        │
│    1. stdin JSON에서 session_id 추출 + sanitize         │
│    2. state/{sid_hash}.json atomic update              │
│    3. $TMUX 있을 때만 tmux_target 캡처                  │
│    4. Stop hook: lockfile 체크 → 데몬 없으면 spawn      │
└─────────────────────────────────────────────────────────┘
                          ↓
        ~/.cache-necromancer/state/{sid_hash}.json
                          ↓
┌─────────────────────────────────────────────────────────┐
│  cache-necromancer 데몬                                 │
│                                                         │
│  싱글톤: ~/.cache-necromancer/daemon.lock               │
│    - fcntl.flock(LOCK_EX|LOCK_NB) 실패 시 즉시 종료     │
│    - PID 기록, stale PID는 os.kill(pid,0) 체크 후 해제  │
│                                                         │
│  메인 루프:                                             │
│    1. time.monotonic() 드리프트 체크 (sleep/wake 감지)  │
│       - 드리프트 > 30초 → 모든 세션 next_refresh_at에 +5분│
│    2. state/*.json 스캔                                 │
│    3. 후보 선별 + fire 전 안전 검증                     │
│    4. mode별 실행 (notify / auto / hybrid)              │
│    5. dynamic sleep: max(1, min(60, next_fire_in))     │
│    6. 모든 세션 1h stale → 자체 종료                    │
│                                                         │
│  fire 안전 검증:                                        │
│    - pane 존재: tmux list-panes -t {target} -F "#{pane_id}" │
│    - pane_pid 살아있음: ps -p {pane_pid}                │
│    - pane_current_command이 claude 계열                 │
│    - pane buffer 빈 마지막 줄 (capture-pane으로 확인)   │
│    - 위 검증 통과 시에만 send-keys                      │
└─────────────────────────────────────────────────────────┘
```

## 디렉토리 구조

```
cache-necromancer/
├── .claude-plugin/
│   └── plugin.json              # 매니페스트 (name + hooks 경로)
├── hooks/
│   └── hooks.json               # hook 이벤트 → command 매핑
├── scripts/                     # 실제 실행되는 Python 스크립트
│   ├── on_stop.py
│   ├── on_user_prompt.py
│   └── on_session_end.py
├── daemon/
│   ├── __main__.py              # `python -m daemon` 진입점
│   ├── poller.py                # 폴링 루프 + 판정
│   ├── refresh.py               # fire (send-keys) + 안전 검증
│   ├── notifier.py              # macOS 알림 + 벨
│   └── clock.py                 # time.monotonic 드리프트 감지
├── lib/
│   ├── state.py                 # atomic JSON read/write + flock
│   ├── config.py                # config.toml 로드
│   ├── lockfile.py              # daemon.lock + stale PID 처리
│   ├── session_id.py            # sanitize / hash
│   ├── tmux.py                  # tmux 명령 wrapper
│   └── logger.py                # daemon.log 회전
├── tests/
│   ├── test_state.py
│   ├── test_session_id.py
│   ├── test_tmux.py
│   ├── test_poller.py
│   ├── test_refresh.py
│   └── test_clock.py
├── config.toml.example
└── README.md
```

## 플러그인 매니페스트 (CRITICAL #1 수정)

### `.claude-plugin/plugin.json`

```json
{
  "$schema": "https://json.schemastore.org/claude-code-plugin-manifest.json",
  "name": "cache-necromancer",
  "version": "0.1.0",
  "description": "Auto-refresh Claude Code prompt cache TTL via minimal tmux injection",
  "author": {
    "name": "Brody Byun"
  },
  "license": "MIT",
  "keywords": ["cache", "tmux", "macos"],
  "hooks": "./hooks/hooks.json"
}
```

플러그인은 `name` + `hooks` 경로만 있으면 동작. `commands`/`agents`/`skills`/`mcpServers`는 없음. `platform`/`tools`/`requires`는 공식 스키마에 없는 필드이므로 제거.

### `hooks/hooks.json`

```json
{
  "description": "Track last response/input time + trigger background refresh daemon",
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_stop.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_user_prompt.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_session_end.py\"",
            "timeout": 5,
            "async": true
          }
        ]
      }
    ]
  }
}
```

- `matcher` 필드는 Stop/UserPromptSubmit/SessionEnd에 의미 없으므로 생략 (이 이벤트들은 tool-specific 매칭이 필요 없음).
- `timeout`은 5초로 명시. 기본값(600초)에 의존하지 않음.
- `SessionEnd`는 `async: true` — Claude Code 종료 대기 시키지 않음.

## 상태 모델 (MAJOR #4, #8 수정)

### 저장 위치

`~/.cache-necromancer/state/{sid_hash}.json`

- `sid_hash` = `sanitize(session_id)`
  - 정규식 `^[a-zA-Z0-9_-]{1,64}$` 통과 시 그대로 사용
  - 실패 시 `sha256(session_id).hexdigest()[:16]`
- 경로 traversal 차단 + 파일시스템 안전

### 스키마

```json
{
  "session_id": "abc123",
  "sid_hash": "abc123",
  "cwd": "/Users/brody/projects/vdit",
  "tmux_target": "main:0.1",
  "last_stop_at": "2026-05-12T14:30:00+09:00",
  "last_user_input_at": "2026-05-12T14:25:00+09:00",
  "last_fire_at": null,
  "refresh_count": 0,
  "next_refresh_at": "2026-05-12T15:25:00+09:00",
  "imminent_notified": false,
  "created_at": "2026-05-12T13:00:00+09:00"
}
```

`next_refresh_at`이 `null`이면 fire 직후 상태 (다음 Stop hook 대기 중). `last_fire_at`은 Stop hook recursion 차단용.

### 동시성 (MAJOR #4)

```python
def update_state(sid_hash, mutator):
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
            data = mutator(data)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, path)  # atomic
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
```

- read-modify-write 전체가 lock 범위
- 쓰기는 임시파일 → `os.replace()` atomic rename
- per-session lock 파일 (`{sid_hash}.lock`)으로 데몬과 격리

### 갱신 판정 (전부 AND)

```python
def is_refresh_candidate(s, now, max_count):
    return (
        s.next_refresh_at is not None
        and s.last_stop_at > s.last_user_input_at
        and now >= s.next_refresh_at
        and s.refresh_count < max_count
        and s.tmux_target is not None
        and (s.last_fire_at is None
             or (now - s.last_fire_at) > timedelta(seconds=5))   # recursion 차단
    )
```

## Stop hook recursion 차단 (MAJOR #7)

문제: fire로 주입된 `.`도 Stop hook을 다시 발사. `refresh_count`가 무한 증가하거나 즉시 fire가 또 트리거될 수 있음.

해법:
1. fire 직후 `last_fire_at = now` 기록.
2. Stop hook이 호출되면 `now - last_fire_at < 5초`일 때 **`refresh_count`를 증가시키지 않고 next_refresh_at만 재설정**. 이건 "내가 주입해서 발생한 응답"의 Stop으로 간주.
3. 위 5초는 fire→응답 종료까지의 정상 범위. 사용자가 5초 이내에 진짜 다른 응답을 끝낸 경우는 무시할 수 있는 엣지 케이스.

## fire 전 안전 검증 (CRITICAL #2)

`daemon/refresh.py:fire()`:

```python
def fire(tmux_target: str, prompt: str = ".") -> bool:
    # 1. pane 존재 확인
    panes = run(["tmux", "list-panes", "-t", tmux_target.split(":")[0],
                 "-F", "#{session_name}:#{window_index}.#{pane_index} #{pane_pid} #{pane_current_command}"])
    if not panes:
        log_warn(f"tmux session not found: {tmux_target}")
        return False
    
    matching = [p for p in panes if p.startswith(tmux_target + " ")]
    if not matching:
        log_warn(f"pane not found: {tmux_target}")
        return False
    
    _, pane_pid, current_cmd = matching[0].split()
    
    # 2. pane 프로세스 살아있는지
    try:
        os.kill(int(pane_pid), 0)
    except (ProcessLookupError, ValueError):
        log_warn(f"pane process dead: pid={pane_pid}")
        return False
    
    # 3. current command이 claude 계열인지
    if "claude" not in current_cmd.lower():
        log_warn(f"pane not running claude: cmd={current_cmd}")
        return False
    
    # 4. pane buffer 마지막 줄이 비어있는지 (사용자 입력 중 아님)
    buffer_tail = run(["tmux", "capture-pane", "-t", tmux_target, "-p", "-S", "-1"])
    if buffer_tail and buffer_tail.strip() and not buffer_tail.strip().endswith(">"):
        # prompt가 아닌 다른 문자열이 마지막 줄에 있음 = 사용자 입력 중
        log_warn(f"pane buffer not clean: {buffer_tail!r}")
        return False
    
    # 5. send-keys 실행
    run(["tmux", "send-keys", "-t", tmux_target, prompt, "Enter"])
    log_info(f"fired: target={tmux_target}")
    return True
```

검증 실패 시 log 경고만 남기고 fire 안 함. 다음 폴링 사이클에서 재시도.

## 타이머 보정 — sleep/wake 처리 (CRITICAL #3)

`daemon/clock.py`:

```python
class DriftDetector:
    def __init__(self, threshold_seconds=30):
        self.last_wall = datetime.now()
        self.last_mono = time.monotonic()
        self.threshold = threshold_seconds
    
    def detect_drift(self) -> int:
        """Returns drift in seconds if sleep/wake suspected, else 0."""
        now_wall = datetime.now()
        now_mono = time.monotonic()
        wall_elapsed = (now_wall - self.last_wall).total_seconds()
        mono_elapsed = now_mono - self.last_mono
        self.last_wall = now_wall
        self.last_mono = now_mono
        # wall clock이 monotonic보다 30초 이상 더 흘렀으면 sleep/wake로 간주
        drift = wall_elapsed - mono_elapsed
        return int(drift) if drift > self.threshold else 0
```

폴링 루프 진입 시:

```python
drift = detector.detect_drift()
if drift > 0:
    log_warn(f"clock drift detected: {drift}s — postponing all refreshes by 5min")
    for state_file in glob_states():
        update_state(parse_sid(state_file), lambda s: postpone(s, minutes=5))
```

- sleep/wake 후 일제히 fire하는 사고 방지
- 5분 유예 후 정상 사이클로 복귀

## 데몬 lifecycle (MAJOR #5)

### lockfile 획득

```python
def acquire_lock(lock_path: Path) -> Optional[IO]:
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # stale PID 체크
        try:
            old_pid = int(lock_path.read_text().strip() or "0")
            if old_pid > 0:
                os.kill(old_pid, 0)  # 살아있으면 OK
                f.close()
                return None
        except (ProcessLookupError, ValueError):
            pass
        # stale → 락 강제 획득 시도
        f.close()
        f = open(lock_path, "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None
    f.write(str(os.getpid()))
    f.flush()
    return f
```

### 데몬 spawn (Stop hook)

```python
def spawn_daemon():
    if (LOCK_PATH).exists():
        try:
            pid = int(LOCK_PATH.read_text().strip() or "0")
            if pid > 0:
                os.kill(pid, 0)
                return  # 이미 실행 중
        except (ProcessLookupError, ValueError):
            pass
    
    subprocess.Popen(
        ["python3", "-m", "daemon"],
        cwd=PLUGIN_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # setsid
        close_fds=True,
    )
```

- stdout/stderr → `/dev/null`로 좀비 방지
- `start_new_session=True`로 부모 프로세스(Claude Code)와 lifecycle 분리

## 폴링 루프 (MAJOR #6)

```python
def run_poll_loop():
    detector = DriftDetector()
    while True:
        # 1. sleep/wake 보정
        drift = detector.detect_drift()
        if drift > 0:
            postpone_all_sessions(minutes=5)
        
        # 2. 상태 수집
        sessions = list(load_all_states())
        if not sessions:
            log_info("no sessions; daemon shutting down")
            return
        
        # 3. 후보 처리
        now = datetime.now(timezone.utc)
        for s in sessions:
            handle_session(s, now)
        
        # 4. pane liveness GC
        for s in sessions:
            if s.tmux_target and not pane_alive(s.tmux_target):
                log_info(f"pane dead, removing state: {s.sid_hash}")
                delete_state(s.sid_hash)
        
        # 5. idle 셧다운
        if all_stale_for(sessions, hours=1):
            log_info("all sessions idle, shutting down")
            return
        
        # 6. dynamic sleep
        next_fire_in = min_next_fire_in(sessions, now)
        sleep_seconds = max(1, min(60, next_fire_in))
        time.sleep(sleep_seconds)
```

`next_fire_in` = 모든 세션 중 `next_refresh_at - now`의 최솟값 (초). 없으면 60.

## 모드별 실행

```python
def execute_mode(s: State, mode: str):
    if mode == "notify":
        notifier.notify(f"🔄 {s.session_id[:8]} 캐시 갱신 시점 도달")
        log_info(f"[would-fire] sid={s.sid_hash} mode=notify")
    
    elif mode == "auto":
        if refresh.fire(s.tmux_target):
            update_state(s.sid_hash, lambda x: {**x,
                "refresh_count": x["refresh_count"] + 1,
                "next_refresh_at": None,
                "last_fire_at": now_iso(),
                "imminent_notified": False,
            })
    
    elif mode == "hybrid":
        notifier.notify(f"🔄 {s.session_id[:8]} {wait}s 내 입력 없으면 자동 갱신")
        sleep_with_cancel(wait, sid_hash=s.sid_hash)  # state 변경 polling
        # 다시 state 읽어서 last_user_input_at 변동 확인
        fresh = load_state(s.sid_hash)
        if fresh.last_user_input_at > s.last_user_input_at:
            log_info(f"[cancel] sid={s.sid_hash} user input during hybrid wait")
        elif refresh.fire(fresh.tmux_target):
            update_state(s.sid_hash, ...)  # 위 auto와 동일
```

`sleep_with_cancel`은 1초 단위 폴링으로 state 변경 감지. 단순 `time.sleep(60)` 대신.

## 설정 파일

`~/.cache-necromancer/config.toml` (config.toml 유지, userConfig 미사용):

```toml
[general]
mode = "hybrid"                       # notify | auto | hybrid
refresh_interval_minutes = 55
max_refresh_count = 10

[refresh]
prompt = "."
hybrid_wait_seconds = 60
recursion_window_seconds = 5

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = 5

[advanced]
daemon_poll_max_seconds = 60
session_ttl_hours = 24
daemon_idle_shutdown_minutes = 60
clock_drift_threshold_seconds = 30
clock_drift_postpone_minutes = 5
```

플러그인 매니페스트의 `userConfig`는 사용 안 함. 이유: TOML이 더 풍부한 표현 가능 + 사용자가 익숙. `${CLAUDE_PLUGIN_ROOT}` 외 추가 추상화 없음.

## 데이터 흐름 (재정리)

### Stop hook

```
stdin: {"session_id": "...", "transcript_path": "...", "cwd": "...", "hook_event_name": "Stop"}

1. sid_hash = sanitize(session_id)
2. with state lock:
     s = load_or_create(sid_hash)
     s.last_stop_at = now
     s.tmux_target = capture_tmux_target() if $TMUX else None
     if s.tmux_target is None:
         exit 0  # tmux 외부 = 비활성
     
     # recursion 판정
     if s.last_fire_at and (now - s.last_fire_at) < 5s:
         # 내가 fire한 turn의 응답 종료
         s.next_refresh_at = now + 55min
         s.last_fire_at = None  # 리셋
     else:
         # 사용자 turn의 정상 응답 종료
         s.next_refresh_at = now + 55min
         s.imminent_notified = False
     
     save(s)
3. log: "[stop] sid=... next=... fire_recursion=..."
4. spawn_daemon_if_dead()
5. exit 0
```

### UserPromptSubmit hook

```
stdin: {..., "prompt": "...", "hook_event_name": "UserPromptSubmit"}

1. sid_hash = sanitize(session_id)
2. with state lock:
     s = load_or_create(sid_hash)
     s.last_user_input_at = now
     save(s)
3. log: "[user] sid=..."
4. exit 0
```

### SessionEnd hook

```
1. sid_hash = sanitize(session_id)
2. delete state/{sid_hash}.json
3. log: "[end] sid=..."
4. exit 0  (async: true)
```

### 데몬 폴링 (요약)

위 "폴링 루프" 섹션 참조.

## 에러 처리 (확장)

| 상황 | 처리 |
|------|------|
| tmux 외부 hook | state 안 만들고 silent exit 0 |
| state JSON 손상 | `.corrupt`로 이름 변경 후 제거, log 경고 |
| state lock acquire 실패 (timeout) | 5초 timeout, 초과 시 log 경고 후 hook exit 0 |
| 데몬 spawn 실패 | hook이 log만 남기고 exit 0 |
| 데몬 중복 기동 | lock + stale PID 처리로 단일 실행 보장 |
| send-keys 실패 (pane 없음) | log + 해당 state 파일 삭제 (pane 영구 사라짐) |
| osascript 실패 | log + 터미널 벨로 fallback |
| 시계 역행 (NTP) | `now < last_stop_at` 시 `last_stop_at = now` 보정 |
| sleep/wake | DriftDetector가 5분 유예 |
| Claude Code 강제 종료 | 데몬이 pane liveness 체크 → 즉시 GC |
| recursion (fire → Stop → fire 무한) | `last_fire_at` 5초 윈도우로 차단 |
| 만료된 캐시 fire | 정상 동작; 새 캐시 생성됨. log에 "cache may be cold" 경고 |

## 테스트 전략

### 단위 테스트

- `lib/state.py`
  - atomic write: 동시 쓰기 시 lost update 없음
  - lock timeout 5초 후 graceful fail
  - 손상 JSON `.corrupt` 백업
- `lib/session_id.py`
  - 정상 sid: pass-through
  - `/`, `..`, 공백 포함 sid: sha256 hash
  - 빈 문자열: 거부
- `lib/lockfile.py`
  - 정상 lock 획득
  - stale PID 감지 후 강제 획득
  - 살아있는 PID는 양보
- `daemon/clock.py`
  - 드리프트 미감지 (정상 sleep)
  - 드리프트 감지 (sleep/wake 시뮬레이션)
- `daemon/refresh.py`
  - 모든 안전 검증 mock으로 통과/실패 시나리오
  - send-keys 호출 verify (subprocess.run mock)
- `daemon/poller.py`
  - 후보 선별 로직 (freezegun)
  - 동적 sleep 계산
  - idle 셧다운

### 통합 테스트

- Hook + state 통합: 실제 stdin JSON → state 파일 변화 검증
- 데몬 단일 사이클: 미리 만든 state 파일 → 판정 + (mock된) fire
- Recursion 시퀀스: Stop → fire → Stop (5초 내) → recursion 차단 검증
- Hybrid cancel: 알림 → 60s 대기 중 user input → 취소 검증
- Sleep/wake 시뮬: monotonic 정지 + wall clock 점프 → 5분 유예 검증

### 수동 검증 (README)

1. `mode=notify`: 55분 대기 → macOS 알림 확인
2. `mode=auto`: 55분 대기 → tmux pane에 `.` 자동 입력 + 캐시 hit 확인 (transcript)
3. `mode=hybrid`: 알림 후 사용자 입력 → 갱신 취소
4. 강제 종료(Ctrl+C로 Claude 종료) → 데몬이 pane 죽음 감지하고 state 정리
5. macOS sleep 1시간 후 wake → 일제히 fire 안 되고 5분 유예 확인
6. Recursion 차단: auto 모드에서 fire 발생 후 Stop이 또 트리거되는데 refresh_count 증가 안 함 확인

도구: pytest + freezegun + 실제 tmux 호출

## 비기능 요구사항

- Hook 실행 시간 < 100ms (Claude Code 응답성 영향 최소화)
- 데몬 메모리 < 50MB
- log 파일은 일자별 회전 (`daemon.log.YYYY-MM-DD`), 7일 후 자동 삭제
- 모든 timestamp는 ISO 8601 + 타임존(`+09:00`) 포함
- Python 3.11+ (TOML 표준 라이브러리 `tomllib` 사용)

## 빌드 단계 (재분해)

### Phase 1 — 기반 + notify (PR ≤300 LOC)
1. 디렉토리 구조, `plugin.json`, `hooks/hooks.json`, `config.toml.example`
2. `lib/session_id.py` + tests
3. `lib/state.py` (atomic write + flock) + tests
4. `lib/lockfile.py` (stale PID 처리) + tests
5. `lib/tmux.py` (tmux 명령 wrapper) + tests
6. `lib/config.py`, `lib/logger.py`
7. `scripts/on_stop.py`, `on_user_prompt.py`, `on_session_end.py`
8. `daemon/notifier.py` (osascript + bell)
9. `daemon/clock.py` (DriftDetector)
10. `daemon/poller.py` (notify 모드만, 최소 폴링 루프)
11. `daemon/__main__.py` (lockfile + run_poll_loop)
12. 통합 테스트 + 수동 시나리오 #1

### Phase 2 — fire + 안전 검증 + auto/hybrid (PR ≤300 LOC)
1. `daemon/refresh.py` (fire + 5단계 안전 검증) + tests
2. `poller.py`에 auto/hybrid 분기 추가
3. Recursion 차단 로직 + tests
4. Sleep/wake 5분 유예 로직 (clock.py 연동)
5. 통합 테스트 + 수동 시나리오 #2~#6

## 한계 (명시)

- 사용자가 타이핑 중인데 Enter 누르지 않은 상태는 감지 불가. tmux pane buffer 마지막 줄로 부분 감지 가능하지만 완벽하지 않음.
- 캐시 hit 보장 불가: Anthropic 캐시 정책 변경 시 갱신 효과 없을 수 있음. log에 cache hit/miss 직접 확인 어려움 (response usage 정보 필요).
- macOS 전용: linux 알림은 v1 이후.
- tmux 외부 (terminal 직접 실행 등): 비활성.
- 동시 실행 Claude Code 인스턴스가 매우 많으면(20+) state 락 경합 가능 — 현실적 사용에서는 문제 없음.

## 미해결 / 추후 결정

- Phase 3 (통계/대시보드)는 별도 spec
- linux 지원은 v1 이후
- monitor (v2.1.105+ 기능)로 데몬 대체 검토 — 현재는 자체 데몬 방식 유지
- Anthropic 캐시 정책 변경 시 대응 매뉴얼

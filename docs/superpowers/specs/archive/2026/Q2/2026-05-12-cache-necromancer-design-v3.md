# cache-necromancer 설계 v3

작성일: 2026-05-12 (v3 개정)
상태: 설계 (구현 전)
이전 버전: v1 `2026-05-12-cache-necromancer-design.md`, v2 `2026-05-12-cache-necromancer-design-v2.md`

**v3 개정 사유**: v2 codex 재리뷰에서 silent failure 위험 MAJOR 3건 + MINOR 2건 발견. (1) daemon lockfile truncate 버그, (2) state lock에서 blocking flock + spec timeout 불일치, (3) fire 안전 검증과 send-keys 사이 race 미처리, (4) recursion guard 경계 표기 혼용, (5) DriftDetector timezone-naive wall clock 사용. v3는 이 5개 항목을 모두 정확히 명세.

**v2 개정 사유 (참고)**: Codex 리뷰로 CRITICAL 3건 / MAJOR 5건 발견. 가장 큰 결함은 `plugin.json` 형식이 공식 스키마와 맞지 않아 플러그인 로드 자체가 불가능했다는 점.

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
7. **Stop hook recursion 차단** → fire 시 환경변수 `CACHE_NECROMANCER_INJECTED=1`을 prompt 앞에 prefix할 수는 없으므로, **state 파일에 `last_fire_at` 기록 + Stop hook이 자기 fire 직후의 Stop인지 (`(now - last_fire_at) <= recursion_window_seconds`) 판정해서 refresh_count 무한 증가 차단** (v3에서 경계 `<=` 포함으로 통일, `last_fire_at` window 경과 시에도 명시적 정리).
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
    "name": "brody424"
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
  "pane_id": "%23",
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

### 동시성 (MAJOR #4 + v3 state lock timeout 통일)

```python
class StateLockTimeout(Exception):
    pass

def acquire_state_lock_with_timeout(lock_path: Path, timeout: float = 5.0) -> IO:
    """Non-blocking flock + deadline retry (10ms 간격). 5초 초과 시 StateLockTimeout."""
    deadline = time.monotonic() + timeout
    # 'a+' 모드: 락 획득 전 truncate 안 함, 락 획득 후 안전하게 read/write
    f = open(lock_path, "a+")
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.monotonic() >= deadline:
                f.close()
                raise StateLockTimeout(f"lock contention >{timeout}s: {lock_path}")
            time.sleep(0.01)

def update_state(sid_hash: str, mutator):
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path, timeout=5.0)
    except StateLockTimeout as e:
        log_warn(f"state lock timeout: {e}")
        return  # hook은 graceful exit 0, 데몬은 다음 사이클에 재시도
    try:
        # 락 획득 후에만 read-modify-write
        data = json.loads(path.read_text()) if path.exists() else {}
        data = mutator(data)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)  # atomic rename (POSIX 보장)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()
```

명세:
- **non-blocking flock + 5초 deadline retry**. blocking `LOCK_EX`는 절대 사용 안 함 (hook timeout 5초와 일치).
- lock 파일은 `a+` 모드 (open만으로 truncate 안 됨). 락 획득 후에만 데이터 파일을 read/write.
- 쓰기는 임시파일 `*.tmp` → `os.replace()` atomic rename (POSIX 보장).
- per-session lock 파일 (`{sid_hash}.lock`)으로 데몬과 격리.
- timeout 시 hook은 log 후 exit 0 경로를 반드시 탄다 (silent 유실 방지).
- `os.replace`는 동일 파일시스템 내 atomic이며, `~/.cache-necromancer/` 내부에서만 사용하므로 안전.

### 갱신 판정 (전부 AND)

판정 로직은 "Stop hook recursion 차단" 섹션의 `is_refresh_candidate`를 단일 소스로 한다 (중복 정의 방지).

## Stop hook recursion 차단 (MAJOR #7 + v3 경계 통일)

문제: fire로 주입된 `.`도 Stop hook을 다시 발사. `refresh_count`가 무한 증가하거나 즉시 fire가 또 트리거될 수 있음.

해법:
1. fire 직후 `last_fire_at = now` 기록.
2. Stop hook이 호출되면 다음 분기:
   - **`now - last_fire_at <= recursion_window_seconds`** (= injected 응답의 Stop으로 간주):
     - `refresh_count` 증가 안 함
     - `next_refresh_at = now + refresh_interval_minutes`
     - **`last_fire_at = None`** (명시적 정리, 다음 사이클에 깨끗하게 시작)
   - **window 초과** (= 사용자 turn의 정상 응답 Stop):
     - `next_refresh_at = now + refresh_interval_minutes`
     - `imminent_notified = False`
     - **`last_fire_at = None`** (window 경과 후에도 명시적 정리, stale 잔존 방지)
3. `recursion_window_seconds`는 config 값으로 노출 (기본 5초). 테스트에서 mock 가능.

**경계 표기 일관성**: spec 전체에서 모든 비교를 `<=` (포함) 또는 `>` (초과)로 통일. `<` / `<=` / `< 5s` / `> 5s` 혼용 금지.

```python
def is_injected_response(s: State, now: datetime, window_sec: int) -> bool:
    if s.last_fire_at is None:
        return False
    return (now - s.last_fire_at).total_seconds() <= window_sec
```

### 갱신 판정 조건도 동일 경계 사용

```python
def is_refresh_candidate(s: State, now: datetime, max_count: int) -> bool:
    return (
        s.next_refresh_at is not None
        and s.last_stop_at > s.last_user_input_at
        and now >= s.next_refresh_at
        and s.refresh_count < max_count
        and s.tmux_target is not None
        and s.pane_id is not None
        and (s.last_fire_at is None
             or (now - s.last_fire_at).total_seconds() > config.recursion_window_seconds)
    )
```

## fire 전 안전 검증 (CRITICAL #2 + v3 race 처리)

### v3 변경
- `tmux_target` 문자열 대신 **불변 식별자 `%pane_id`**(tmux globally unique pane id)로 dispatch.
- 5단계 검증 → send-keys 사이의 race를 줄이기 위해 **send-keys 직전에 동일한 pane_id/pane_pid/current_command를 재확인**.
- `subprocess.run(..., check=True)` 실패는 명시적으로 처리해 fire 실패 시 False 반환 + 해당 세션 비활성화 정책.
- race 완전 제거 불가능 → 한계 섹션에 명시.

### state에 `pane_id` 추가

Stop hook이 `tmux_target` 캡처 시 `pane_id`도 함께 기록:

```python
def capture_tmux_target() -> Optional[dict]:
    if not os.environ.get("TMUX"):
        return None
    out = subprocess.run(
        ["tmux", "display-message", "-p",
         "-F", "#{session_name}:#{window_index}.#{pane_index}|#{pane_id}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    target, pane_id = out.split("|")
    return {"tmux_target": target, "pane_id": pane_id}  # e.g. "%23"
```

state 스키마에 `pane_id: "%23"` 필드 추가.

### `daemon/refresh.py:fire()`

```python
import os, subprocess
from typing import Optional, Tuple

PaneInfo = Tuple[str, str, str]  # (pane_id, pane_pid, current_cmd)

def query_pane_by_id(pane_id: str) -> Optional[PaneInfo]:
    """tmux 전체에서 pane_id로 검색. 없으면 None."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a",
             "-F", "#{pane_id}|#{pane_pid}|#{pane_current_command}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None
    for line in out.splitlines():
        pid_field, pane_pid, cmd = line.split("|", 2)
        if pid_field == pane_id:
            return pid_field, pane_pid, cmd
    return None

def is_pane_safe_to_inject(pane_id: str) -> Tuple[bool, Optional[PaneInfo]]:
    """5단계 검증. 통과 시 (True, info), 실패 시 (False, None)."""
    info = query_pane_by_id(pane_id)
    if not info:
        log_warn(f"pane gone: {pane_id}")
        return False, None
    pid_field, pane_pid, current_cmd = info

    # 1. pane PID 살아있는지
    try:
        os.kill(int(pane_pid), 0)
    except (ProcessLookupError, ValueError):
        log_warn(f"pane process dead: pid={pane_pid}")
        return False, None

    # 2. current command이 claude 계열인지
    if "claude" not in current_cmd.lower():
        log_warn(f"pane not running claude: cmd={current_cmd}")
        return False, None

    # 3. pane buffer 마지막 줄이 비어있는지 (휴리스틱 — 사용자 입력 중 아님)
    try:
        tail = subprocess.run(
            ["tmux", "capture-pane", "-t", pane_id, "-p", "-S", "-1"],
            check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError:
        log_warn(f"capture-pane failed for {pane_id}")
        return False, None
    last = tail.strip()
    if last and not last.endswith((">", "│", "❯", "$", "#")):
        log_warn(f"pane buffer not clean: {last!r}")
        return False, None

    return True, info

def fire(state: dict, prompt: str = ".") -> Tuple[bool, str]:
    """Returns (success, reason). reason은 log/디버깅용 + 호출자가 정책 결정에 사용."""
    pane_id = state.get("pane_id")
    if not pane_id:
        return False, "no_pane_id"

    # 1차 검증
    ok, info = is_pane_safe_to_inject(pane_id)
    if not ok:
        return False, "pre_check_failed"
    pre_pid, pre_proc_pid, pre_cmd = info

    # 2차 재확인 (send-keys 직전, race 최소화)
    ok2, info2 = is_pane_safe_to_inject(pane_id)
    if not ok2:
        return False, "recheck_failed"
    if info2 != info:
        log_warn(f"pane changed between checks: {info} -> {info2}")
        return False, "pane_drift"

    # 3. send-keys (check=True로 명시 실패 처리)
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", pane_id, prompt, "Enter"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        log_warn(f"send-keys failed: {e.stderr}")
        return False, "send_keys_failed"

    log_info(f"fired: pane_id={pane_id}")
    return True, "ok"
```

### 실패 처리 정책

- `pre_check_failed` / `recheck_failed`: log 경고. 해당 세션 비활성화 안 함 (일시적일 수 있음). 다음 폴링 사이클에 재시도.
- `pane_drift`: log 경고. 다음 사이클 재시도.
- `pane_gone` (`query_pane_by_id`가 None) 또는 `pane process dead`: state 파일 삭제 (영구 사라짐).
- `send_keys_failed`: log 경고. 한 사이클 더 재시도. 연속 3회 실패 시 state 비활성화 (`tmux_target = None`).

### 한계 (race)

5단계 검증 → 재확인 → send-keys 사이에는 여전히 수 ms~수십 ms의 race window가 존재한다. 이 시간에:
- 사용자가 타이핑을 시작하면 `.` + Enter가 사용자 입력에 끼어들 가능성.
- pane이 종료되면 send-keys가 실패 (check=True로 잡힘).

이는 tmux 외부 동기화 메커니즘 없이는 완전 제거 불가. 현실적 사용에서 race window 내 사용자 입력 확률은 매우 낮음 (50ms 정도). 사용자 알림 + log로 사후 추적 가능.

## 타이머 보정 — sleep/wake 처리 (CRITICAL #3 + v3 monotonic-only)

### v3 변경
DriftDetector는 **`time.monotonic()` 측정값만으로 sleep/wake 추론**. wall clock(`datetime.now()`)은 DST/NTP step/수동 시각 변경에 취약하므로 drift 계산에서 제외. wall clock은 로깅 전용으로만 사용.

### 원리
- `time.monotonic()`은 시스템 sleep 시간을 포함하지 않거나 포함하는 동작이 OS마다 다른데, **macOS `time.monotonic()`은 sleep 시간 포함**.
- **`time.monotonic()` 단독으로 sleep 감지 불가**. 대신 "기대된 sleep 시간 vs 실제 monotonic 경과" 비교.
- 즉 데몬이 `sleep(N)`을 부르면 정상적으로 `N` 초만큼 monotonic이 흐른다. 만약 `N + threshold` 이상 흘렀다면 OS sleep으로 간주.

`daemon/clock.py`:

```python
import time
import os
from datetime import datetime, timezone

class DriftDetector:
    """sleep/wake를 'expected sleep vs actual monotonic elapsed' 비교로 감지."""

    def __init__(self, threshold_seconds: int = 30):
        self.threshold = threshold_seconds
        self.last_mono: Optional[float] = None
        self.last_expected_sleep: float = 0.0

    def mark_sleep_start(self, expected_seconds: float) -> None:
        """time.sleep(N) 호출 직전에 등록."""
        self.last_mono = time.monotonic()
        self.last_expected_sleep = expected_seconds

    def detect_after_sleep(self) -> int:
        """time.sleep 직후 호출. 비정상적 지연 = sleep/wake로 간주.
        Returns drift seconds (0 if normal).
        """
        if self.last_mono is None:
            return 0
        actual = time.monotonic() - self.last_mono
        drift = actual - self.last_expected_sleep
        # log wall clock for forensics (drift 계산엔 사용 안 함)
        if drift > self.threshold:
            log_warn(
                f"sleep/wake suspected: expected={self.last_expected_sleep:.1f}s "
                f"actual={actual:.1f}s drift={drift:.1f}s wall={datetime.now(timezone.utc).isoformat()}"
            )
            return int(drift)
        return 0
```

### 폴링 루프 통합

```python
detector = DriftDetector(threshold_seconds=config.clock_drift_threshold_seconds)

while True:
    # ... 후보 처리 ...

    next_fire_in = min_next_fire_in(sessions, now)
    sleep_seconds = max(1.0, min(60.0, next_fire_in))

    detector.mark_sleep_start(sleep_seconds)
    time.sleep(sleep_seconds)
    drift = detector.detect_after_sleep()
    if drift > 0:
        postpone_all_sessions(minutes=config.clock_drift_postpone_minutes)
```

명세:
- drift 계산에 `datetime.now()`/wall clock 사용 안 함. DST/NTP step 무관.
- wall clock 역행 시에도 monotonic 기반이라 drift 음수 발생 안 함.
- 첫 사이클은 `last_mono=None`이므로 detect 안 함 (false positive 방지).
- 5분 유예는 모든 세션의 `next_refresh_at`을 `now + postpone_minutes`로 미룸 (이미 도달한 세션은 미루기, 미래 세션은 그대로).

## 데몬 lifecycle (MAJOR #5 + v3 lockfile 버그 + PID 재사용 방어)

### 문제 (v2)
- `open(lock_path, "w")`는 lock 획득 실패 전에 파일 truncate. 이후 PID 읽으려 해도 사라짐.
- `os.kill(pid, 0)`만 보고 "실행 중"으로 판단하면 PID 재사용 시 무관한 프로세스를 데몬으로 오인.

### 해법 (v3)
- lock 파일은 `a+` 모드로 열어 truncate 안 됨.
- 락 획득 후에만 PID + process start time(`ps -o lstart=`)을 함께 기록.
- liveness 체크 시 PID + start_time 둘 다 비교해서 재사용 PID 판별.

### lockfile 획득 / liveness 헬퍼

```python
import os, fcntl, subprocess, json, time
from pathlib import Path
from typing import Optional, IO

def proc_start_time(pid: int) -> Optional[str]:
    """ps -o lstart= -p PID. 죽은 프로세스면 None."""
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return out or None
    except subprocess.CalledProcessError:
        return None

def is_daemon_alive(lock_path: Path) -> bool:
    """lockfile 내용(JSON: {pid, started}) + start_time 일치 검증."""
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        return False
    try:
        meta = json.loads(lock_path.read_text())
        pid = int(meta["pid"])
        started = meta["started"]
    except (json.JSONDecodeError, KeyError, ValueError):
        return False
    current = proc_start_time(pid)
    return current is not None and current == started

def acquire_daemon_lock(lock_path: Path) -> Optional[IO]:
    """단일 데몬 보장. 살아있는 데몬 있으면 None. stale은 강제 회수."""
    # 'a+'로 열어 락 획득 전 truncate 안 함
    f = open(lock_path, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # 다른 프로세스가 lock 잡고 있음. 살아있으면 양보.
        f.close()
        if is_daemon_alive(lock_path):
            return None
        # stale lock — 잠깐 기다린 후 강제 회수 시도
        f = open(lock_path, "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None  # 다른 프로세스가 동시에 회수 시도 중
    # 락 획득 완료 → 안전하게 truncate 후 PID + start_time 기록
    f.seek(0)
    f.truncate()
    pid = os.getpid()
    started = proc_start_time(pid)
    f.write(json.dumps({"pid": pid, "started": started}))
    f.flush()
    return f
```

### 데몬 spawn (Stop hook)

```python
def spawn_daemon_if_needed():
    if is_daemon_alive(LOCK_PATH):
        return  # 살아있음
    # liveness 실패 = 죽음 OR 처음 기동. spawn.
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

명세:
- stdout/stderr → `/dev/null`로 좀비/파이프 차단.
- `start_new_session=True`로 부모(Claude Code) lifecycle 분리.
- spawn 후 즉시 return. 데몬이 실제 lock을 잡는 건 약 50ms 이내. 짧은 race window는 데몬의 acquire_daemon_lock이 처리.
- 정상 종료 시 데몬이 `lock_path.unlink()` + `fcntl.flock(LOCK_UN)`로 정리.

## 폴링 루프 (MAJOR #6 + v3 DriftDetector 통합)

```python
def run_poll_loop(config: Config):
    detector = DriftDetector(threshold_seconds=config.clock_drift_threshold_seconds)
    while True:
        # 1. 상태 수집
        sessions = list(load_all_states())
        if not sessions:
            log_info("no sessions; daemon shutting down")
            return

        # 2. pane liveness GC (pane_id 기반)
        for s in sessions:
            if s.pane_id and not query_pane_by_id(s.pane_id):
                log_info(f"pane dead, removing state: {s.sid_hash}")
                delete_state(s.sid_hash)
        sessions = [s for s in sessions if state_exists(s.sid_hash)]

        # 3. 후보 처리 + mode 실행
        now = datetime.now(timezone.utc)
        for s in sessions:
            handle_session(s, now, config)

        # 4. idle 셧다운
        if all_stale_for(sessions, minutes=config.daemon_idle_shutdown_minutes):
            log_info("all sessions idle, shutting down")
            return

        # 5. dynamic sleep
        next_fire_in = min_next_fire_in(sessions, now)
        sleep_seconds = max(1.0, min(float(config.daemon_poll_max_seconds), next_fire_in))

        # 6. sleep + sleep/wake 감지
        detector.mark_sleep_start(sleep_seconds)
        time.sleep(sleep_seconds)
        drift = detector.detect_after_sleep()
        if drift > 0:
            postpone_all_sessions(minutes=config.clock_drift_postpone_minutes)
```

- `next_fire_in` = 모든 세션 중 `(next_refresh_at - now).total_seconds()`의 양의 최솟값. 없으면 `daemon_poll_max_seconds`.
- pane liveness GC를 매 사이클 수행해 24h GC 의존도 낮춤 (MINOR #12).
- DriftDetector는 sleep 직후에만 평가해 첫 사이클 false positive 방지.

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
2. captured = capture_tmux_target()  # None if $TMUX 없음
   if captured is None:
       log_info("[stop] tmux 외부, 비활성")
       exit 0

3. try acquire_state_lock_with_timeout(timeout=5.0)
   except StateLockTimeout: log_warn + exit 0

4. with state lock:
     s = load_or_create(sid_hash)
     s.last_stop_at = now
     s.tmux_target = captured["tmux_target"]
     s.pane_id = captured["pane_id"]
     window = config.recursion_window_seconds

     if is_injected_response(s, now, window):
         # injected Stop: refresh_count 유지, next_refresh_at 재설정
         s.next_refresh_at = now + timedelta(minutes=config.refresh_interval_minutes)
         s.last_fire_at = None        # 명시적 정리
         was_injected = True
     else:
         # 사용자 turn의 정상 응답 Stop
         s.next_refresh_at = now + timedelta(minutes=config.refresh_interval_minutes)
         s.imminent_notified = False
         s.last_fire_at = None        # window 경과 시에도 명시적 정리 (stale 잔존 방지)
         was_injected = False

     save(s)

5. log: f"[stop] sid={sid_hash} next={s.next_refresh_at} injected={was_injected}"
6. spawn_daemon_if_needed()
7. exit 0
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

# cache-necromancer 설계 v5 (headless CLI 기반)

작성일: 2026-05-13
v5.1 업데이트: 2026-05-13 — codex v5 리뷰 MAJOR 9 + MINOR 3 인라인 반영
상태: 설계 (구현 전)
이전 버전: v1 / v2 / v3 / v4 (PTY 주입 시대, 폐기)

**v5 개정 사유**: 실험으로 `claude -p "." --resume <id> --fork-session --no-session-persistence` 1줄이 캐시 hit + TTL 갱신을 일으킴이 확인됨 (cache_read 46,115 tokens, 원본 jsonl 무영향, 디스크 흔적 없음). 이로 인해 v4의 PTY 주입 / 5단계 안전 검증 / 어댑터 패턴 / recursion 차단 등 약 50%가 불필요해짐. v5는 headless CLI 기반으로 단순화 + PRD v3의 신뢰성 요구(`/cn:status`, `/cn:dry-run`, 인지 가능한 실패) 반영.

**v5.1 변경 (codex v5 리뷰 반영)**: 9가지 핵심 결함 수정:
- 스케줄러 정합성: 성공 fire 후 `next_refresh_at`을 데몬이 직접 갱신 (watchdog 의존 안 함)
- transient 실패 시 exponential backoff + jitter
- CACHE_COLD / AUTH_ERROR 복구 경로 추가 (disabled 마커, delete 대신 보존)
- transcript bounded tail (Stop hook 100ms 보장)
- `current_turn_started_at` 신설 (after_fire 판정 정확화)
- UserPromptSubmit `allow_create=False` (불완전 state 생성 차단)
- 디스크 흔적 보장 문구 정확화 ("원본 transcript 무변경" / "fork transcript 임시 생성 가능")
- `CLAUDE_CODE_SESSION_ID` 환경변수로 `/cn:status` 현재 세션 식별

**관련 문서**: PRD v3 `2026-05-12-cache-necromancer-PRD.md`

---

## 개요

Claude Code 플러그인. 데몬이 백그라운드에서 `claude -p` headless CLI로 짧은 프롬프트를 보내 캐시 hit을 일으켜 TTL을 1시간 연장.

핵심: **사용자가 보는 인터랙티브 세션을 절대 건드리지 않음**. fire는 별도 프로세스 + fork session + no-persistence라:
- **원본 transcript JSONL: 절대 무변경 보장** (인터랙티브 세션 영향 0)
- **fork transcript: claude CLI 내부에서 일시 생성될 수 있음** — `--no-session-persistence` 덕분에 claude CLI 프로세스 종료 시 정리됨. 백업 도구/인덱서/보안 스캐너가 그 짧은 윈도우 동안 잡을 가능성은 있음. v1은 이를 cleanup 의무로 보지 않음 (claude CLI 자체 책임).

---

## 결정 요약

| 항목 | 결정 |
|------|------|
| 구현 언어 | Python 3.11+ |
| 형태 | Claude Code 플러그인 (`.claude-plugin/plugin.json` + `hooks/hooks.json`) |
| 갱신 메커니즘 | `claude -p "." --resume <sid> --fork-session --no-session-persistence` |
| MVP 범위 | notify / auto / hybrid 3 모드 + `/cn:status`, `/cn:dry-run` 명령 |
| `max_refresh_count` 기본값 | 10 (~10시간) |
| 환경 의존 | tmux 무관, **모든 터미널** 동작. macOS 1차, Linux는 알림 어댑터만 추가 시 가능 |
| 세션 ID | hook JSON의 `session_id` (sanitize 후 사용) |
| 데몬 실행 | Hook 레이지 기동 (lockfile + PID + start_time) |
| 상태 락 | per-session `fcntl.flock` non-blocking + 4초 deadline |
| 알림 채널 | macOS 시스템 알림 + 터미널 벨 |
| 데몬 종료 | 모든 세션 1시간 stale 시 자체 종료 |
| 로그 | fire log + user_turn log (raw, Phase 4 대시보드용) |

---

## 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│  Claude Code 인스턴스 (각 인터랙티브 세션 1개)             │
│                                                          │
│  hooks/hooks.json 등록:                                  │
│    Stop hook             → on_stop.py                    │
│    UserPromptSubmit hook → on_user_prompt.py             │
│    SessionEnd hook       → on_session_end.py             │
│                                                          │
│  hook 호출:                                              │
│    1. stdin JSON에서 session_id 추출 + sanitize          │
│    2. state/{sid_hash}.json atomic update                │
│    3. Stop hook: 데몬 살아있는지 확인, 없으면 spawn       │
└──────────────────────────────────────────────────────────┘
                          ↓
        ~/.cache-necromancer/state/{sid_hash}.json
                          ↓
┌──────────────────────────────────────────────────────────┐
│  cache-necromancer 데몬 (lazy, lockfile 단일 인스턴스)   │
│                                                          │
│  메인 루프 (동적 sleep):                                  │
│    1. 모든 state 파일 스캔                                │
│    2. 후보 판정 (next_refresh_at 도달 + 한도 미달)        │
│    3. mode별 실행 (notify / auto / hybrid)               │
│    4. fire = subprocess.run([                            │
│         "claude", "-p", config.prompt,                   │
│         "--resume", session_id,                          │
│         "--fork-session",                                │
│         "--no-session-persistence",                      │
│         "--output-format", "json"])                      │
│    5. 응답 JSON에서 cache_read_input_tokens 추출 → log   │
│    6. fire 후 watchdog (응답/Stop 미수신 시 복구)        │
│    7. 동적 sleep (next_fire_in 또는 60s)                 │
│    8. 모든 세션 1h stale → 데몬 종료                      │
└──────────────────────────────────────────────────────────┘
```

핵심 차이 (vs v4):
- ❌ tmux 의존 / 어댑터 패턴 / 5단계 안전 검증 / PaneInfo / pane race / send-keys
- ✅ `claude -p` 호출 1줄 + 응답 JSON 파싱 + cache_read 검증

---

## 컴포넌트 구조

```
cache-necromancer/
├── .claude-plugin/
│   └── plugin.json              # 매니페스트
├── hooks/
│   └── hooks.json               # 이벤트 → command 매핑
├── commands/
│   ├── cn:status.md             # /cn:status 슬래시 명령
│   └── cn:dry-run.md            # /cn:dry-run 슬래시 명령
├── scripts/
│   ├── on_stop.py               # Stop hook 엔트리
│   ├── on_user_prompt.py        # UserPromptSubmit hook 엔트리
│   ├── on_session_end.py        # SessionEnd hook 엔트리
│   ├── cn_status.py             # /cn:status 백엔드
│   └── cn_dry_run.py            # /cn:dry-run 백엔드
├── daemon/
│   ├── __main__.py              # `python -m daemon` 진입점
│   ├── poller.py                # 폴링 루프 + 판정
│   ├── refresh.py               # claude -p 호출 + 결과 파싱
│   ├── notifier.py              # macOS 알림 + 벨
│   ├── clock.py                 # time.monotonic DriftDetector
│   ├── watchdog.py              # fire→Stop 누락 복구
│   └── transcript.py            # transcript jsonl 마지막 turn usage 추출
├── lib/
│   ├── state.py                 # atomic JSON read/write + flock
│   ├── config.py                # config.toml 로드
│   ├── lockfile.py              # daemon.lock + stale PID 처리
│   ├── session_id.py            # sanitize / hash
│   └── logger.py                # fire/user_turn log 회전
├── tests/
└── README.md
```

**책임 분리**
- `hooks/` + `scripts/*` — Claude Code 엔트리, timestamp만 기록.
- `daemon/*` — 폴링 + claude -p 호출 + 사이드 이펙트.
- `lib/*` — 순수 함수 위주, 테스트 용이.
- `commands/*` — 슬래시 명령 (사용자가 `/cn:status` 등으로 호출).

---

## 플러그인 매니페스트

### `.claude-plugin/plugin.json`

```json
{
  "$schema": "https://json.schemastore.org/claude-code-plugin-manifest.json",
  "name": "cache-necromancer",
  "version": "0.1.0",
  "description": "Auto-refresh Claude Code prompt cache TTL via headless CLI",
  "author": {"name": "Brody Byun"},
  "license": "MIT",
  "keywords": ["cache", "cost", "macos"],
  "hooks": "./hooks/hooks.json"
}
```

### `hooks/hooks.json`

```json
{
  "description": "Track session timestamps to drive background cache refresh",
  "hooks": {
    "Stop": [
      {"hooks": [{
        "type": "command",
        "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_stop.py\"",
        "timeout": 5
      }]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{
        "type": "command",
        "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_user_prompt.py\"",
        "timeout": 5
      }]}
    ],
    "SessionEnd": [
      {"hooks": [{
        "type": "command",
        "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_session_end.py\"",
        "timeout": 5,
        "async": true
      }]}
    ]
  }
}
```

- 모든 hook timeout 5초 명시 (기본 600초 의존 안 함).
- SessionEnd는 `async: true`로 Claude Code 종료 차단 안 함.

---

## 상태 모델

### 저장 위치
`~/.cache-necromancer/state/{sid_hash}.json`

`sid_hash` 계산:
- 정규식 `^[a-zA-Z0-9_-]{1,64}$` 통과 시 그대로 사용
- 실패 시 `sha256(session_id).hexdigest()[:16]`
- 목적: 경로 traversal 차단 + 파일시스템 안전

### 스키마

```json
{
  "session_id": "abc123",
  "sid_hash": "abc123",
  "transcript_path": "/Users/.../abc123.jsonl",
  "cwd": "/Users/brody/projects/vdit",
  "last_stop_at": "2026-05-12T14:30:00+09:00",
  "last_user_input_at": "2026-05-12T14:25:00+09:00",
  "current_turn_started_at": null,
  "last_fire_at": null,
  "refresh_count": 0,
  "next_refresh_at": "2026-05-12T15:25:00+09:00",
  "imminent_notified": false,
  "consecutive_fire_failures": 0,
  "last_fire_reason": null,
  "backoff_until": null,
  "disabled": false,
  "disabled_reason": null,
  "disabled_at": null,
  "cache_cold_retries": 0,
  "created_at": "2026-05-12T13:00:00+09:00"
}
```

**필드 설명 (v5.1 신설)**:
- `current_turn_started_at`: UserPromptSubmit 시점에 기록. **현재 진행 중인 turn 시작 시각**. `last_user_input_at`은 매번 덮어쓰지만 이건 turn 동안 유지됨. Stop hook이 turn 종료 시 `last_user_input_at`을 덮어쓰기 직전의 값을 보존하는 용도. `after_fire` 판정에 사용.
- `backoff_until`: transient 실패 시 exponential backoff. `next_refresh_at`과 별개로 "이 시각 전엔 재시도 금지" 가드.
- `disabled` / `disabled_reason` / `disabled_at`: AUTH_ERROR 또는 연속 5회 실패 / CACHE_COLD 2회 retry 후 영구 비활성화. `delete_state` 대신 보존해 `/cn:status`에서 원인 확인 가능.
- `cache_cold_retries`: CACHE_COLD 발생 횟수. 2회 도달하면 영구 disabled (1회는 일시적 가능성 인정).

**상태 의미**:
- `next_refresh_at`이 `null` AND `last_fire_at`도 `null` → 신규 세션 또는 disabled
- `next_refresh_at`이 `null` AND `last_fire_at`이 채워짐 → fire 직후 watchdog 복구 대기 (예외 케이스. v5.1에서 정상 fire는 next_refresh_at 직접 갱신하므로 발생 빈도 매우 낮음)
- `disabled=true` → 후보에서 영구 제외. `/cn:status`로 원인 확인 가능.

### 동시성

```python
STATE_LOCK_DEADLINE = 4.0   # hook timeout(5s) - cleanup margin(1s)

def acquire_state_lock_with_timeout(lock_path: Path,
                                    timeout: float = STATE_LOCK_DEADLINE) -> IO:
    """Non-blocking flock + 10ms 간격 retry. timeout 초과 시 StateLockTimeout."""
    deadline = time.monotonic() + timeout
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

def update_state(sid_hash: str, mutator, *, allow_create: bool = False):
    """allow_create=False: 파일 없으면 write 생략 (SessionEnd 후 stale 재생성 차단)."""
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout as e:
        log_warn(f"state lock timeout: {e}")
        return
    try:
        if not path.exists():
            if not allow_create:
                log_info(f"state already deleted, skip: {sid_hash}")
                return
            data = {}
        else:
            data = json.loads(path.read_text())
        data = mutator(data)
        if data is None:
            return  # mutator abort
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)  # POSIX atomic
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

def delete_state(sid_hash: str):
    """SessionEnd / GC가 호출. per-session lock 후 삭제."""
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout as e:
        log_warn(f"delete_state lock timeout: {e}")
        return
    try:
        if path.exists():
            path.unlink()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()
```

호출자별 `allow_create`:
- `on_stop.py`, `on_user_prompt.py` → `True` (신규 세션 생성 OK)
- `daemon/*` (poller, watchdog, refresh) → `False`

### 갱신 판정 (전부 AND, v5.1)

```python
INTERACTIVE_INPUT_QUIET_SECONDS = 30  # 인터랙티브 input 직후 N초간 fire 금지 (rate limit 경쟁 완화)

def is_refresh_candidate(s: State, now: datetime, config) -> bool:
    if s.disabled:
        return False
    if s.next_refresh_at is None:
        return False
    if now < s.next_refresh_at:
        return False
    if s.refresh_count >= config.max_refresh_count:
        return False
    if s.backoff_until is not None and now < s.backoff_until:
        return False  # transient 실패 후 backoff 중
    # rate limit 경쟁 완화: 사용자 input 직후 30초 내 fire 금지
    if (now - s.last_user_input_at).total_seconds() < INTERACTIVE_INPUT_QUIET_SECONDS:
        return False
    return True
```

**v5.1 변경**: `disabled` / `backoff_until` 가드 + 인터랙티브 input quiet window 추가. `consecutive_fire_failures` 한도는 `disabled` 마커로 통합.

**v4 → v5 변경 (참고)**: `last_stop_at > last_user_input_at` 비교 제거. headless는 인터랙티브 화면 안 건드리니 사용자 작업 중 보호는 `next_refresh_at` 자연 갱신만으로 충분.

---

## 핵심 메커니즘 — fire

### `daemon/refresh.py`

```python
import subprocess, json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class FireReason(str, Enum):
    OK = "ok"
    CACHE_COLD = "cache_cold"              # cache_read=0 (캐시 이미 만료)
    NETWORK_ERROR = "network_error"        # 네트워크 / 일시적 API 오류
    AUTH_ERROR = "auth_error"              # 인증/권한 오류 (영구)
    PROCESS_ERROR = "process_error"        # subprocess 자체 실패 (claude 미설치 등)
    TIMEOUT = "timeout"                    # claude -p 응답 timeout
    BAD_OUTPUT = "bad_output"              # JSON 파싱 실패

# v5.1: BAD_OUTPUT은 transient로 분류 (claude CLI 일시 버그 가능성).
# 단, BAD_OUTPUT 카운터가 2회 누적되면 별도 영구 disable (스키마 변경 가능성).
TRANSIENT_REASONS = {
    FireReason.NETWORK_ERROR,
    FireReason.TIMEOUT,
    FireReason.PROCESS_ERROR,
    FireReason.BAD_OUTPUT,
}
PERMANENT_REASONS = {FireReason.AUTH_ERROR}

# AUTH 감지 패턴 확장 (v5.1 MAJOR #4)
AUTH_ERROR_PATTERNS = (
    "authentication", "unauthorized", "login required",
    "credential", "api key", "expired token", "forbidden",
)

@dataclass
class FireResult:
    success: bool
    reason: FireReason
    cache_read: int = 0
    cache_create: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: Optional[str] = None
    raw_stdout: str = ""

def fire(state: dict, config) -> FireResult:
    """claude -p 헤드레스 호출. 결과 JSON에서 usage 추출."""
    cmd = [
        "claude", "-p", config.refresh.prompt,
        "--resume", state["session_id"],
        "--fork-session",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=config.refresh.fire_timeout_seconds,  # 기본 120s
            cwd=state.get("cwd"),  # 원본 세션의 cwd로 실행 (auth/credential 정합)
        )
    except subprocess.TimeoutExpired:
        return FireResult(success=False, reason=FireReason.TIMEOUT)
    except (FileNotFoundError, PermissionError) as e:
        return FireResult(success=False, reason=FireReason.PROCESS_ERROR,
                          raw_stdout=str(e)[:500])

    if proc.returncode != 0:
        stderr_lower = proc.stderr.lower()
        if any(p in stderr_lower for p in AUTH_ERROR_PATTERNS):
            return FireResult(success=False, reason=FireReason.AUTH_ERROR,
                              raw_stdout=proc.stderr[:500])
        return FireResult(success=False, reason=FireReason.NETWORK_ERROR,
                          raw_stdout=proc.stderr[:500])

    try:
        data = json.loads(proc.stdout)
        usage = data.get("usage", {})
        result = FireResult(
            success=True,
            reason=FireReason.OK,
            cache_read=usage.get("cache_read_input_tokens", 0),
            cache_create=usage.get("cache_creation_input_tokens", 0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            model=next(iter(data.get("modelUsage", {}).keys()), None),
        )
        # cache_read = 0이면 캐시 이미 만료 (실패는 아니지만 의미 없음)
        if result.cache_read == 0:
            result.success = False
            result.reason = FireReason.CACHE_COLD
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return FireResult(success=False, reason=FireReason.BAD_OUTPUT,
                          raw_stdout=proc.stdout[:500])
```

### 호출 후 결과 처리 (v5.1 — 스케줄러 정합성 + backoff + 복구 경로)

```python
import random
from datetime import datetime, timedelta, timezone

def _backoff_seconds(failure_count: int, base: float = 30.0, cap: float = 1800.0) -> float:
    """exponential backoff with jitter. 30s, 60s, 120s, ... cap 30min."""
    exp = min(cap, base * (2 ** (failure_count - 1)))
    return exp * (0.5 + random.random() * 0.5)  # ±25% jitter

def disable_session(s: State, reason: str, message: str, *, notify: bool = True):
    """delete 대신 disabled 마커로 보존. /cn:status에서 원인 확인 가능."""
    now = datetime.now(timezone.utc)
    update_state(s.sid_hash, lambda x: {**x,
        "disabled": True,
        "disabled_reason": reason,
        "disabled_at": now.isoformat(),
        "next_refresh_at": None,
        "last_fire_at": None,
        "last_fire_reason": reason,
    }, allow_create=False)
    if notify:
        notifier.notify(message)
    log_warn(f"[disabled] sid={s.sid_hash} reason={reason}")

def handle_fire_result(s: State, result: FireResult, config) -> None:
    max_fail = config.advanced.consecutive_fire_failures_disable  # 기본 5
    max_cache_cold_retries = config.advanced.cache_cold_max_retries  # 기본 2
    refresh_min = config.refresh_interval_minutes
    now = datetime.now(timezone.utc)

    # 1. 모든 결과를 fire log에 기록 (Phase 4 raw data)
    log_fire(s, result, now)

    if result.success:
        # v5.1 핵심 수정 (MAJOR #1): 다음 갱신 시점을 데몬이 직접 설정.
        # headless fire는 Stop hook을 만들지 않으므로 next_refresh_at 자동 갱신 안 됨.
        # watchdog은 예외 복구 전용으로 둠.
        update_state(s.sid_hash, lambda x: {**x,
            "refresh_count": x["refresh_count"] + 1,
            "next_refresh_at": (now + timedelta(minutes=refresh_min)).isoformat(),
            "last_fire_at": now.isoformat(),
            "imminent_notified": False,
            "consecutive_fire_failures": 0,
            "cache_cold_retries": 0,
            "backoff_until": None,
            "last_fire_reason": result.reason.value,
        }, allow_create=False)
        return

    # 실패 분기

    # 영구 실패 (AUTH_ERROR): disabled 마커로 보존 (delete 안 함)
    if result.reason in PERMANENT_REASONS:
        disable_session(
            s, reason=result.reason.value,
            message=(f"🛑 cache-necromancer: {s.session_id[:8]} "
                     f"인증 오류로 비활성화. `/cn:status`로 확인."),
        )
        return

    # CACHE_COLD: 1회는 일시적 가능성 (스키마/timing) → retry. 2회 누적 시 영구 disable.
    if result.reason == FireReason.CACHE_COLD:
        new_retries = s.cache_cold_retries + 1
        if new_retries >= max_cache_cold_retries:
            disable_session(
                s, reason="cache_cold_persistent",
                message=(f"💀 cache-necromancer: {s.session_id[:8]} "
                         f"캐시가 계속 cold 상태. 비활성화. `/cn:status`로 확인."),
            )
            return
        # 1회 retry: backoff 후 다음 사이클 재시도. refresh_count 증가 안 함.
        backoff = _backoff_seconds(new_retries, base=120.0, cap=600.0)
        log_warn(f"[cache_cold] sid={s.sid_hash} retry {new_retries}/{max_cache_cold_retries} "
                 f"in {backoff:.0f}s")
        update_state(s.sid_hash, lambda x: {**x,
            "cache_cold_retries": new_retries,
            "backoff_until": (now + timedelta(seconds=backoff)).isoformat(),
            "last_fire_reason": result.reason.value,
        }, allow_create=False)
        return

    # 일시적 실패 (TRANSIENT_REASONS): exponential backoff + 카운터 증가
    if result.reason in TRANSIENT_REASONS:
        new_count = s.consecutive_fire_failures + 1
        backoff = _backoff_seconds(new_count)
        update_state(s.sid_hash, lambda x: {**x,
            "consecutive_fire_failures": new_count,
            "backoff_until": (now + timedelta(seconds=backoff)).isoformat(),
            "last_fire_reason": result.reason.value,
        }, allow_create=False)

        # 3회 연속 → 알림 (인지 가능한 실패)
        if new_count == 3:
            notifier.notify(
                f"⚠️ cache-necromancer: {s.session_id[:8]} 3회 연속 실패 "
                f"({result.reason.value}). 다음 시도까지 {backoff:.0f}s."
            )
        # 5회 연속 → 영구 비활성화
        if new_count >= max_fail:
            disable_session(
                s, reason=f"consecutive_failures_{result.reason.value}",
                message=(f"🛑 cache-necromancer: {s.session_id[:8]} "
                         f"{max_fail}회 연속 실패로 비활성화. `/cn:status`로 확인."),
                notify=True,
            )
        return

    # 도달 안 함 (모든 reason 분기 처리 완료)
    log_warn(f"[unhandled_fire_reason] sid={s.sid_hash} reason={result.reason}")
```

**v5.1 변경 요약 (MAJOR #1, #2, #3, #4)**:
- 성공 fire 후 `next_refresh_at`을 데몬이 직접 갱신 → watchdog 의존 제거.
- 실패 시 `backoff_until` 설정 → 즉시 재시도 안 함.
- CACHE_COLD: 1회 retry 허용 후 영구 disable (스키마/timing 일시적 가능성 인정).
- AUTH_ERROR: `delete_state` 대신 `disabled` 마커 보존 → `/cn:status`에서 원인 확인 가능.
- 모든 영구 비활성화는 `disable_session()` 헬퍼를 통과해 disabled_reason 기록.

---

## fire 후 watchdog

`auto`/`hybrid` 모드에서 fire가 성공해도 응답 도중 Claude API 오류 등으로 Stop hook이 누락될 수 있음. 그러면 `next_refresh_at`이 영원히 `None`으로 남아 세션 영구 정지.

```python
FIRE_STOP_WATCHDOG_SECONDS = 120

def watchdog_check(s: State, now: datetime, config):
    if s.next_refresh_at is not None or s.last_fire_at is None:
        return  # 정상 상태
    elapsed = (now - s.last_fire_at).total_seconds()
    if elapsed > config.advanced.fire_stop_watchdog_seconds:
        log_warn(f"watchdog: fire→Stop missing for {elapsed:.0f}s, "
                 f"recovering sid={s.sid_hash}")
        update_state(s.sid_hash, lambda x: {**x,
            "next_refresh_at": (now + timedelta(
                minutes=config.refresh_interval_minutes
            )).isoformat(),
            "last_fire_at": None,
            "imminent_notified": False,
        }, allow_create=False)
```

`refresh_count`는 증가시키지 않음 (이미 한 번 fire한 것). watchdog 복구 직후 늦게 Stop hook이 도착하면 `last_fire_at`이 이미 `None`이라 정상 Stop 흐름.

**v4의 recursion 차단은 불필요해짐**: headless fire는 인터랙티브 Claude Code의 Stop hook을 발사하지 않음 (별도 프로세스라 hook 이벤트 안 옴). 그래서 `last_fire_at` 5초 윈도우 체크 같은 메커니즘 제거.

---

## DriftDetector — sleep/wake 보정

```python
import time

class DriftDetector:
    """sleep/wake를 'expected sleep vs actual monotonic elapsed' 비교로 감지."""

    def __init__(self, threshold_seconds: int = 30):
        self.threshold = threshold_seconds
        self.last_mono: Optional[float] = None
        self.last_expected_sleep: float = 0.0

    def mark_sleep_start(self, expected_seconds: float) -> None:
        self.last_mono = time.monotonic()
        self.last_expected_sleep = expected_seconds

    def detect_after_sleep(self) -> int:
        if self.last_mono is None:
            return 0
        actual = time.monotonic() - self.last_mono
        drift = actual - self.last_expected_sleep
        if drift > self.threshold:
            log_warn(f"sleep/wake suspected: expected={self.last_expected_sleep:.1f}s "
                     f"actual={actual:.1f}s drift={drift:.1f}s")
            return int(drift)
        return 0
```

`time.monotonic()` 단독 기반. wall clock(DST/NTP step) 무관. 데몬 부팅 후 첫 `mark_sleep_start()` 이후 sleep부터 정상 감지.

---

## 데몬 lifecycle

### lockfile (`~/.cache-necromancer/daemon.lock`)

```python
def proc_start_time(pid: int) -> Optional[str]:
    """ps -o lstart=. macOS/linux 호환."""
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                             check=True, capture_output=True, text=True).stdout.strip()
        return out or None
    except subprocess.CalledProcessError:
        return None

def is_daemon_alive(lock_path: Path) -> bool:
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        return False
    try:
        meta = json.loads(lock_path.read_text())
        pid, started = int(meta["pid"]), meta["started"]
    except (json.JSONDecodeError, KeyError, ValueError):
        return False
    current = proc_start_time(pid)
    return current is not None and current == started  # PID + start_time 동시 일치

def acquire_daemon_lock(lock_path: Path) -> Optional[IO]:
    """단일 데몬 보장. stale은 강제 회수."""
    f = open(lock_path, "a+")  # truncate 안 됨
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        if is_daemon_alive(lock_path):
            return None
        # stale → 재시도
        f = open(lock_path, "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None
    # 락 획득 후 PID + start_time 기록
    f.seek(0)
    f.truncate()
    pid = os.getpid()
    f.write(json.dumps({"pid": pid, "started": proc_start_time(pid)}))
    f.flush()
    return f
```

### 데몬 spawn (Stop hook)

```python
def spawn_daemon_if_needed():
    if is_daemon_alive(LOCK_PATH):
        return
    subprocess.Popen(
        ["python3", "-m", "daemon"],
        cwd=PLUGIN_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
```

`start_new_session=True`로 부모 Claude Code lifecycle과 분리. `/dev/null` redirect로 좀비/파이프 차단.

---

## 폴링 루프

```python
def run_poll_loop(config):
    if not acquire_daemon_lock(LOCK_PATH):
        log_info("another daemon alive, exit")
        return

    detector = DriftDetector(threshold_seconds=config.advanced.clock_drift_threshold_seconds)

    while True:
        # 1. 상태 수집
        sessions = list(load_all_states())
        if not sessions:
            log_info("no sessions; daemon shutting down")
            return

        now = datetime.now(timezone.utc)

        # 2. watchdog (fire→Stop 누락 복구)
        for s in sessions:
            watchdog_check(s, now, config)

        # 3. 후보 처리 + mode 실행
        for s in sessions:
            handle_session(s, now, config)

        # 4. idle 셧다운
        if all_stale_for(sessions, minutes=config.advanced.daemon_idle_shutdown_minutes):
            log_info("all sessions idle, shutting down")
            return

        # 5. dynamic sleep
        next_fire_in = min_next_fire_in(sessions, now)
        sleep_seconds = max(1.0, min(float(config.advanced.daemon_poll_max_seconds),
                                      next_fire_in))

        # 6. sleep + sleep/wake 감지
        detector.mark_sleep_start(sleep_seconds)
        time.sleep(sleep_seconds)
        drift = detector.detect_after_sleep()
        if drift > 0:
            postpone_all_sessions(minutes=config.advanced.clock_drift_postpone_minutes)
```

`min_next_fire_in` = `(next_refresh_at - now).total_seconds()`의 양의 최솟값. 없으면 `daemon_poll_max_seconds`.

---

## 모드별 실행

```python
def handle_session(s: State, now: datetime, config):
    if not is_refresh_candidate(s, now, config.max_refresh_count):
        # 임박 알림만 별도 처리
        if (s.next_refresh_at and not s.imminent_notified
            and now >= s.next_refresh_at - timedelta(minutes=config.notify.imminent_threshold_minutes)):
            notify_imminent(s, config)
        return

    execute_mode(s, config.mode, config)

def execute_mode(s: State, mode: str, config):
    if mode == "notify":
        if s.imminent_notified:
            return  # 이미 이번 윈도우에서 알림
        notifier.notify(f"💀 {s.session_id[:8]} 캐시 갱신 시점 도달 (notify만)")
        log_info(f"[would-fire] sid={s.sid_hash} mode=notify")
        update_state(s.sid_hash, lambda x: {**x, "imminent_notified": True},
                     allow_create=False)

    elif mode == "auto":
        result = refresh.fire(s.to_dict(), config)
        handle_fire_result(s, result, config)

    elif mode == "hybrid":
        notifier.notify(f"💀 {s.session_id[:8]} {config.refresh.hybrid_wait_seconds}s "
                        f"내 입력 없으면 자동 갱신")
        cancelled = sleep_with_cancel(
            config.refresh.hybrid_wait_seconds,
            sid_hash=s.sid_hash,
            initial_user_input_at=s.last_user_input_at,
        )
        if cancelled:
            log_info(f"[cancel] sid={s.sid_hash}")
            return
        fresh = load_state(s.sid_hash)
        if fresh is None:
            return
        result = refresh.fire(fresh.to_dict(), config)
        handle_fire_result(fresh, result, config)

def sleep_with_cancel(seconds: float, sid_hash: str,
                       initial_user_input_at: datetime) -> bool:
    """1초 단위 폴링으로 사용자 입력 감지. UserPromptSubmit hook이
    last_user_input_at을 갱신하므로 그 변화로 cancel 판정."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(1.0)
        fresh = load_state(sid_hash)
        if fresh is None:
            return True
        if fresh.last_user_input_at > initial_user_input_at:
            return True
    return False
```

---

## Hook 흐름

### Stop hook (`on_stop.py`) — v5.1

```
stdin: { session_id, transcript_path, cwd, hook_event_name: "Stop", ... }

1. sid_hash = sanitize(session_id)
2. transcript usage 추출 (bounded tail, ≤100ms):
     usage = extract_last_turn_usage(stdin["transcript_path"])
3. update_state(sid_hash, stop_mutator, allow_create=True)
     # Stop hook이 유일한 세션 생성 권한 보유 (필수 필드 모두 채움).

   def stop_mutator(x):
       prev_user_input = x.get("last_user_input_at")
       prev_turn_start = x.get("current_turn_started_at")
       prev_last_fire = x.get("last_fire_at")

       # after_fire 판정 (v5.1 MAJOR #7):
       # 현재 turn 시작 시점 이전에 마지막 fire가 있었으면 = "necromancer 살린 캐시 활용"
       after_fire = (
           prev_turn_start is not None
           and prev_last_fire is not None
           and parse_iso(prev_last_fire) < parse_iso(prev_turn_start)
       )

       # user_turn log 기록 (Phase 2부터)
       if usage and prev_turn_start:
           log_user_turn(sid_hash, x.get("session_id"), usage, after_fire, now)

       return {
           **x,
           "session_id": stdin["session_id"],
           "sid_hash": sid_hash,
           "transcript_path": stdin["transcript_path"],
           "cwd": stdin["cwd"],
           "last_stop_at": now.isoformat(),
           "next_refresh_at": (now + timedelta(
               minutes=config.refresh_interval_minutes)).isoformat(),
           "imminent_notified": False,
           "current_turn_started_at": None,    # turn 종료 → 다음 input 대기
           # last_fire_at는 건드리지 않음 (watchdog/after_fire 판정용)
           "created_at": x.get("created_at", now.isoformat()),
       }

4. log [stop] sid=... next=... after_fire=...
5. spawn_daemon_if_needed()
6. exit 0
```

**v5.1 변경 (MAJOR #7, #8)**:
- `current_turn_started_at`은 UserPromptSubmit에서 설정되고 Stop에서 None으로 클리어. **이 turn 동안만 유효**.
- after_fire 판정: `last_fire_at < current_turn_started_at` (현재 turn 시작 전에 fire가 있었는가).
- Stop hook이 유일한 세션 생성 권한. session_id / sid_hash / transcript_path / cwd / created_at 모두 채움.

### UserPromptSubmit hook (`on_user_prompt.py`) — v5.1

```
stdin: { session_id, transcript_path, cwd, prompt, hook_event_name: "UserPromptSubmit" }

1. sid_hash = sanitize(session_id)
2. update_state(sid_hash,
       mutator=lambda x: {**x,
           "last_user_input_at": now.isoformat(),
           "current_turn_started_at": now.isoformat(),   # turn 시작 (v5.1)
       },
       allow_create=False)   # v5.1: 세션 생성 권한 없음 (Stop만).
   # Stop hook이 한 번도 발화 안 한 신규 세션엔 state 파일이 없음. → skip.
   # (실무: 신규 세션의 첫 input → 첫 응답 → Stop hook → state 생성 → 이후 input부터 정상 추적)
3. log [user] sid=... (state 미존재 시 skip log)
4. exit 0
```

**v5.1 변경 (MAJOR #8)**:
- `allow_create=False` → 신규 세션의 첫 input은 state 파일 못 만듦. 첫 Stop hook이 정식으로 생성.
- 단점: 첫 사용자 input은 추적 안 됨 (~5분의 손실). 첫 fire는 첫 Stop 이후 55분.
- 장점: 모든 state가 완전 필드 보유. `/cn:status`, idle shutdown, fire 후보 판정 모두 안전.

### SessionEnd hook (`on_session_end.py`)

```
1. sid_hash = sanitize(session_id)
2. delete_state(sid_hash)  # per-session lock 획득 후 삭제
3. log [end] sid=...
4. exit 0  (async: true)
```

---

## 로그 (Phase 4 대시보드 raw data)

### fire log — 매 fire 결과

위치: `~/.cache-necromancer/fire.log.YYYY-MM-DD`

형식 (pipe-separated):
```
2026-05-12T22:30:15+09:00 | fire | sid=a4f8c2 | model=opus-4-7 | reason=ok | cache_read=45844 | cache_create=271 | input=6 | output=253
```

reason 값: `ok` / `cache_cold` / `network_error` / `auth_error` / `timeout` / `process_error` / `bad_output`

### user_turn log — 사용자 input 후 응답 종료 시 (Phase 2)

위치: `~/.cache-necromancer/user_turn.log.YYYY-MM-DD`

UserPromptSubmit + Stop hook 페어로 추적. Stop hook이 transcript_path에서 마지막 assistant turn의 usage를 읽어 기록:

```
2026-05-12T22:45:00+09:00 | user_turn | sid=a4f8c2 | model=opus-4-7 | cache_read=45844 | cache_create=125 | input=8 | output=512 | after_fire=true
```

`after_fire` 판정: Stop hook 시점에 `(now - s.last_user_input_at) > config.advanced.user_idle_threshold_minutes` (기본 55분) 이고 그 사이에 fire가 있었으면 `true`.

### `daemon/transcript.py` — transcript jsonl 마지막 turn 추출 (v5.1 bounded tail)

**문제 (codex MAJOR #6)**: transcript JSONL을 처음부터 끝까지 순회하면 긴 세션에선 5초 hook timeout 초과 위험. Stop hook 비기능 요구사항은 `< 100ms`.

**해법**: Stop hook은 **파일 끝에서 bounded tail 역방향 탐색**만 수행. 마지막 N KB만 읽고 가장 최근 assistant 메시지의 usage 추출.

```python
import os
from pathlib import Path
from typing import Optional, Iterator
import json

TAIL_BYTES = 64 * 1024     # 마지막 64KB만 읽음 (대부분 assistant turn 1개 안에 포함)
MAX_REVERSE_LINES = 200    # 안전 한도

def _read_tail(path: Path, max_bytes: int) -> str:
    """파일 끝에서 max_bytes만 읽음. UTF-8 boundary 안전 처리."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        offset = max(0, size - max_bytes)
        f.seek(offset)
        chunk = f.read()
    # UTF-8 multi-byte boundary 안전: 첫 번째 newline 이후부터 사용
    if offset > 0:
        idx = chunk.find(b"\n")
        if idx >= 0:
            chunk = chunk[idx + 1:]
    try:
        return chunk.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""

def extract_last_turn_usage(transcript_path: Path) -> Optional[dict]:
    """transcript JSONL 끝에서 역방향으로 가장 최근 assistant usage 탐색.
    100ms 이내 완료 보장 (64KB read + 최대 200줄 파싱).
    """
    if not transcript_path or not transcript_path.exists():
        return None
    try:
        tail = _read_tail(transcript_path, TAIL_BYTES)
    except (OSError, PermissionError):
        return None

    lines = tail.splitlines()[-MAX_REVERSE_LINES:]
    # 역방향 탐색: 가장 최근 assistant 메시지
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry_type = entry.get("type") or entry.get("role")
        if entry_type != "assistant":
            continue
        usage = (
            entry.get("message", {}).get("usage")
            or entry.get("usage")
        )
        if usage:
            return usage
    return None
```

**Stop hook이 호출**: ~50ms 이내 완료. 64KB는 대부분 assistant turn 한 개를 포함. 만약 매우 큰 단일 응답이 64KB를 초과하면 (드문 케이스) usage 못 찾고 None 반환 → user_turn log 그 turn은 누락 (acceptable degradation).

**전체 transcript 파싱은 비동기 daemon job**: Phase 4 대시보드 영역에서 별도 처리 (Stop hook 안에서 안 함).

**민감정보 미기록**: log에는 토큰 수와 sid_hash만. 사용자 프롬프트 내용, 응답 본문, 파일 경로, cwd 절대 기록 안 함. 7일 후 자동 삭제 (logger 회전).

---

## 슬래시 명령

### `/cn:status`

`commands/cn:status.md` (markdown 파일 — Claude Code가 슬래시 명령으로 인식):

```markdown
---
description: cache-necromancer 추적 상태 확인
allowed-tools: Bash
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cn_status.py"`
```

**현재 세션 식별 (v5.1 MAJOR #5)**: Claude Code는 Bash tool 서브프로세스에 `CLAUDE_CODE_SESSION_ID` 환경변수를 노출함. `cn_status.py`는 `os.environ.get("CLAUDE_CODE_SESSION_ID")`로 현재 세션을 확인하고, 그 세션을 `(this)`로 마킹. 환경변수가 없으면 `(this)` 표시 생략 (best-effort).

`scripts/cn_status.py` 출력 예시:

```
cache-necromancer 상태
─────────────────────
데몬: 살아있음 (PID 12345, 시작 2026-05-12 12:00:00)
추적 중인 세션: 3개 (active 2, disabled 1)

[1] sid=a4f8c2 (this)
    last_stop_at:        2026-05-12 14:30:00
    current_turn:        없음 (idle)
    next_refresh_at:     2026-05-12 15:25:00 (in 5m 12s)
    refresh_count:       3 / 10
    last_fire:           14:25:00 (cache_read=45,844 ✅)
    consecutive_failures: 0
    backoff_until:       —

[2] sid=b5g9d3
    last_stop_at:        2026-05-12 13:50:00
    current_turn:        시작 14:46:00 (사용자 input 응답 대기 중)
    next_refresh_at:     2026-05-12 14:45:00 (스케줄됨)
    refresh_count:       1 / 10
    last_fire:           14:30:00 (cache_read=42,100 ✅)
    consecutive_failures: 0

[3] sid=c6h0e4  🛑 DISABLED
    disabled_reason:     auth_error
    disabled_at:         2026-05-12 14:10:00
    조치:                claude --version 확인 후 인증 갱신
                         그 후 새 세션을 시작하면 자동 추적 재개

최근 24h fire 통계: 12회 (성공 10, cache_cold retry 1, network_error 1)
설정: mode=hybrid, max_refresh_count=10
```

`(this)` 마킹은 슬래시 명령이 Bash tool로 실행될 때 `CLAUDE_CODE_SESSION_ID`가 노출되는 것에 의존. 노출 안 되면 (다른 트리거 경로) 표시 생략.

### `/cn:dry-run`

`commands/cn:dry-run.md`:

```markdown
---
description: 실제 fire 안 하고 다음 갱신 시점 시뮬레이션
allowed-tools: Bash
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cn_dry_run.py"`
```

출력 예시:
```
[dry-run] 모든 추적 세션에 대해 fire 시뮬레이션 (실제 호출 없음)

[1] sid=a4f8c2
    will fire at: 2026-05-12 15:25:00 (in 5m)
    command:      claude -p "." --resume <sid> --fork-session --no-session-persistence
    mode:         hybrid (60s 대기 후 fire)
    estimated cost: ~정상 1턴의 10.7%

설정 변경하려면 ~/.cache-necromancer/config.toml 편집.
mode를 'notify'로 바꾸면 fire 안 함 (알림만).
```

---

## 설정 파일

`~/.cache-necromancer/config.toml`:

```toml
[general]
mode = "hybrid"                              # notify | auto | hybrid
refresh_interval_minutes = 55
max_refresh_count = 10

[refresh]
prompt = "."
hybrid_wait_seconds = 60
fire_timeout_seconds = 120                  # claude -p subprocess timeout

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = 5

[advanced]
daemon_poll_max_seconds = 60
session_ttl_hours = 24                       # stale state GC
daemon_idle_shutdown_minutes = 60
clock_drift_threshold_seconds = 30
clock_drift_postpone_minutes = 5
fire_stop_watchdog_seconds = 120
consecutive_fire_failures_disable = 5        # 5회 연속 실패 시 자동 비활성화
cache_cold_max_retries = 2                   # v5.1: CACHE_COLD 2회 누적 시 영구 disable
backoff_base_seconds = 30.0                  # v5.1: transient 실패 시 exponential backoff 기본
backoff_cap_seconds = 1800.0                 # v5.1: backoff 최대 (30분)
interactive_input_quiet_seconds = 30         # v5.1: 사용자 input 후 N초 fire 금지
state_lock_deadline_seconds = 4.0
```

---

## 에러 처리

| 상황 | 처리 |
|------|------|
| state JSON 손상 | `.corrupt`로 백업 후 제거, log 경고 |
| state lock acquire 실패 (timeout) | 4초 deadline 초과 시 log + hook exit 0 |
| 데몬 spawn 실패 | hook이 log만 남기고 exit 0. 일별 1회 사용자 알림 |
| 데몬 중복 기동 | lockfile + PID + start_time으로 단일 실행 보장 |
| claude CLI 미설치 | `FireReason.PROCESS_ERROR` → 연속 실패 카운터 |
| 네트워크 오류 | `NETWORK_ERROR` → 3회 알림, 5회 자동 비활성화 |
| 인증 오류 (auth_error) | 즉시 비활성화 + 사용자 알림 (영구) |
| 캐시 이미 만료 (cache_read=0) | `CACHE_COLD` → 1회 retry (backoff 후) → 2회 누적 시 영구 disabled |
| fire 응답 timeout (120s) | `TIMEOUT` → 일시적 실패 카운트 |
| transcript jsonl 손상 | usage 추출 실패 → user_turn log 없이 진행 |
| 시계 역행 (NTP) | DriftDetector가 monotonic 기반이라 무관 |
| sleep/wake | 5분 유예 |
| SessionEnd ↔ update_state race | `delete_state()` lock + `update_state(allow_create=False)` 안전망 |

---

## 테스트 전략

### 단위 테스트
- `lib/state.py`: atomic write / lock timeout / 손상 복구 / allow_create
- `lib/session_id.py`: 정상 / 특수문자 / 빈 문자열
- `lib/lockfile.py`: 정상 lock / stale PID / start_time mismatch
- `daemon/refresh.py`: fire 응답 파싱 / 모든 FireReason 분기 (subprocess mock)
- `daemon/clock.py`: 정상 / drift 감지 / 첫 사이클 false positive 방지
- `daemon/watchdog.py`: 정상 상태 / 시간 초과 복구
- `daemon/transcript.py`: jsonl 마지막 assistant turn / 손상 jsonl / 빈 파일

### 통합 테스트
- Hook + state 통합: stdin JSON → state 파일 변화 검증
- 데몬 단일 사이클: 가짜 state → 후보 판정 → mock된 fire
- Hybrid cancel: 알림 → 60s 대기 중 user input → 취소
- fire→Stop watchdog: fire 성공 → Stop hook 없음 → 120s 후 자동 복구
- FireReason 정책: PERMANENT → delete / CACHE_COLD → cease / TRANSIENT → counter
- delete_state ↔ update_state race: 동시 호출 → 일관된 결과
- Sleep/wake 시뮬: monotonic 정지 → 5분 유예

### 수동 검증 (README 기재)
1. `mode=notify`: 55분 대기 → macOS 알림 + `/cn:status` 확인
2. `mode=auto`: 55분 대기 → fire 발생 + `daemon.log`에 cache_read > 0 기록
3. `mode=hybrid`: 알림 + 사용자 input → cancel 확인
4. `/cn:dry-run`: 실제 fire 없음 + 다음 시점 표시
5. 강제 종료: Ctrl+C → 데몬이 SessionEnd 누락 감지하고 GC
6. macOS sleep 1h → wake → 일제히 fire 안 되고 5분 유예
7. 인증 오류 시뮬: PATH에서 `claude` 일시 제거 → 3회 실패 알림 + 5회 비활성화

도구: pytest + freezegun + 실제 `claude -p` 호출 (CI 비용 적음, hello만)

---

## 비기능 요구사항

- Hook 실행 시간 < 100ms
- 데몬 메모리 < 50MB
- 데몬 CPU 사용률 < 1% (대부분 sleep)
- log 파일 일자별 회전, 7일 후 자동 삭제
- 모든 timestamp ISO 8601 + 타임존
- Python 3.11+ (`tomllib` 표준 라이브러리)
- `claude` CLI v2.x 이상 (`--resume`, `--fork-session`, `--no-session-persistence`, `-p` 지원)

---

## 빌드 단계 (PR 분해, v5.1 — 기능 단위)

PR 라인 수보다 **"이 PR이 완료되면 검증할 수 있는 것"** 단위로 분해. 각 PR은 그 자체로 동작 + 테스트 통과.

### Phase 1a — 상태/락/세션ID 기반 (PR 1)
- `lib/session_id.py` + tests (sanitize + sha256 fallback)
- `lib/state.py` (atomic + flock + allow_create) + tests
- `lib/lockfile.py` (stale PID + start_time) + tests
- `lib/config.py`, `lib/logger.py`
- `.claude-plugin/plugin.json` + `config.toml.example`
- **검증**: 단위 테스트 통과. 동시 쓰기 / stale PID / 손상 JSON 시나리오 모두 통과.

### Phase 1b — Hook + 데몬 골격 + notify 모드 (PR 2)
- `hooks/hooks.json`
- `scripts/on_stop.py`, `on_user_prompt.py`, `on_session_end.py`
- `daemon/notifier.py` (osascript + bell)
- `daemon/clock.py` (DriftDetector) + tests
- `daemon/poller.py` (notify 모드만)
- `daemon/__main__.py` (lockfile + run_poll_loop)
- fire.log 골격 (notify는 imminent 알림만 기록)
- **검증**: 실제 Claude Code에서 55분 후 macOS 알림 발생 + 데몬 자동 기동/종료.

### Phase 1c — `/cn:status` 명령 (PR 3)
- `commands/cn:status.md` + `scripts/cn_status.py`
- `CLAUDE_CODE_SESSION_ID` 환경변수 활용 + `(this)` 마킹
- 데몬 상태 / 추적 세션 / disabled 세션 표시
- **검증**: `/cn:status` 호출 시 v5.1 출력 예시와 동일한 결과.

### Phase 2a — fire 호출 + FireReason 분기 (PR 4)
- `daemon/refresh.py` (claude -p 호출 + JSON 파싱) + tests (subprocess mock)
- `FireResult` dataclass + 7개 `FireReason` 모든 분기
- AUTH_ERROR 패턴 감지 + `disable_session()` 헬퍼
- **검증**: 단위 테스트 + 실제 `claude -p hi` 통합 테스트 (cache_read 측정 확인).

### Phase 2b — auto/hybrid 모드 + 스케줄러 (PR 5)
- `handle_fire_result` (성공 시 next_refresh_at 직접 갱신, 실패 시 backoff)
- exponential backoff + jitter (`_backoff_seconds`)
- `INTERACTIVE_INPUT_QUIET_SECONDS=30` 가드
- poller에 auto/hybrid 분기 + `sleep_with_cancel`
- CACHE_COLD 1회 retry → 2회 누적 시 disable
- **검증**: 자동 fire 발생 + 실패 시 backoff 대기 + 연속 5회 자동 disable.

### Phase 2c — watchdog + user_turn log + `/cn:dry-run` (PR 6)
- `daemon/watchdog.py` (예외 복구 전용, fire→Stop 누락 시)
- `daemon/transcript.py` (bounded tail, 100ms 이내)
- `current_turn_started_at` 기반 `after_fire` 판정
- user_turn log 기록 (Phase 4 raw data)
- `commands/cn:dry-run.md` + `scripts/cn_dry_run.py`
- 연속 실패 알림 (3회 / 5회) + AUTH_ERROR 즉시 알림
- **검증**: 모든 수동 시나리오 (PRD v3 6개) 통과 + log에서 Net saved 추정 가능.

### Phase 3 — 공개 배포 준비 (PR 7)
- `marketplace.json`
- `userConfig` 활용한 첫 설치 시 모드 안내
- README (설치 / 추천 사용 패턴 / 안전성 확인 / 트러블슈팅)
- LICENSE (MIT), CHANGELOG, ISSUE_TEMPLATE
- 데모 GIF (선택)
- **검증**: 외부 사용자가 `/plugin install` 한 줄로 설치 후 README만 보고 안전하게 사용 시작.

**v5.1 변경 (MINOR #3)**: 라인 수 목표 제거. PR 7개로 세분화 (1a/1b/1c/2a/2b/2c/3). 각 PR은 단일 검증 가능한 기능 단위.

---

## 한계 (사용자에게 명시)

- **캐시 hit 보장 불가**: Anthropic 캐시 정책이 변경되면 fire 효과 없을 수 있음. CACHE_COLD 2회 누적 시 영구 disable.
- **사용자 타이핑 중 입력 끼어듦은 헤드레스라 발생 안 함**: fire는 별도 프로세스라 인터랙티브 화면 영향 0. 단:
  - fire가 점유하는 동안 단기 네트워크 / Anthropic API rate limit이 인터랙티브 호출과 경쟁 가능. v5.1은 `INTERACTIVE_INPUT_QUIET_SECONDS=30`으로 사용자 input 후 30초 내 fire 금지 → 경쟁 완화.
- **자동 비용 최적화 없음**: v1은 시간 기반 fire만. 사용 패턴 분석은 v0.2 대시보드에서.
- **모델별 가격 동적 계산 없음**: log에는 토큰 수만. Phase 4에서 가격 테이블 곱.
- **fork session transcript 일시 생성**: claude CLI 내부에서 `--no-session-persistence`로 처리되지만, 프로세스 실행 중인 짧은 윈도우 동안 디스크에 일시 파일이 있을 수 있음. v1은 이를 명시적 책임으로 보지 않음 (claude CLI 자체 정리에 위임).
- **신규 세션의 첫 input은 추적 안 됨**: UserPromptSubmit `allow_create=False` (불완전 state 방지). 첫 Stop hook 발화 이후부터 정식 추적 시작 (~5분 손실).
- **transcript bounded tail (64KB)을 초과하는 큰 응답의 usage는 누락 가능**: 매우 드문 케이스. user_turn log에 해당 turn만 빠짐 (절약 모델 추정에 미세 영향).

---

## 미해결 / 추후 결정

- Phase 4 통계/대시보드 (별도 spec)
- Linux 알림 어댑터 (`notify-send`, Phase 4)
- Anthropic 캐시 정책 변경 시 대응 매뉴얼
- monitor 플러그인 컴포넌트(v2.1.105+)로 데몬 대체 검토 — 현재는 자체 데몬 유지

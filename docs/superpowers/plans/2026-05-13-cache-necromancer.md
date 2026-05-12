# cache-necromancer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code의 1시간 프롬프트 캐시 TTL을 헤드레스 CLI (`claude -p --resume`)로 자동 갱신하는 macOS 플러그인. 사용자 화면 안 건드림, 캐시 hit 자동 검증, 인지 가능한 실패 정책.

**Architecture:**
- Hook 3개(Stop/UserPromptSubmit/SessionEnd)가 세션별 JSON state 파일에 timestamp 기록 + 데몬 lazy spawn.
- 데몬이 lockfile 단일 인스턴스로 폴링, 시점 도달 시 `subprocess.run(["claude", "-p", ".", "--resume", sid, "--fork-session", "--no-session-persistence"])`로 fire.
- 응답 JSON의 cache_read 토큰으로 갱신 검증. 실패는 backoff + 누적 카운터로 인지 가능한 실패 처리.

**Tech Stack:** Python 3.11+ (tomllib, fcntl), Claude Code CLI v2.x, macOS (osascript), pytest + freezegun.

**Reference Documents:**
- PRD: `docs/superpowers/specs/2026-05-12-cache-necromancer-PRD.md`
- TECH_SPEC v5.1: `docs/superpowers/specs/2026-05-12-cache-necromancer-design-v5.md`

---

## 작업 원칙

- **TDD**: Red → Green → Refactor. 모든 task가 실패하는 test 먼저, 그 다음 구현.
- **PR 1개 = 1 기능**. 7개 PR로 분해. 각 PR은 독립 검증 가능.
- **커밋 시각**: 이 세션 동안 모든 커밋에 `+9시간` 타임존 보정 적용.
- **commit 메시지**: `feat:` / `test:` / `docs:` / `fix:` 접두사 + 한글 설명.
- **사용자 승인**: 각 PR이 끝나면 사용자 코드리뷰 + 머지 승인 받기.

---

## PR 분해 개요 (7개 PR)

| # | Phase | 산출물 | 검증 기준 |
|---|---|---|---|
| 1 | 1a | `lib/` 모듈 (state, lockfile, session_id, config, logger) + `.claude-plugin/plugin.json` + config.toml.example | 단위 테스트 통과: 동시 쓰기 / stale PID / 손상 JSON / sid sanitize |
| 2 | 1b | `hooks/hooks.json` + `scripts/on_*.py` + `daemon/{notifier,clock,poller,__main__}.py` (notify 모드만) | 실제 Claude Code에서 55분 후 macOS 알림 + 데몬 자동 기동/종료 |
| 3 | 1c | `commands/cn:status.md` + `scripts/cn_status.py` | `/cn:status` 호출 시 데몬 상태 / 추적 세션 / disabled 세션 표시 |
| 4 | 2a | `daemon/refresh.py` (fire + FireReason 분기 + disable_session) | `claude -p` 실제 호출 통합 테스트 + 모든 FireReason mock 분기 |
| 5 | 2b | `handle_fire_result` (auto/hybrid + backoff + interactive quiet window) | 자동 fire + backoff 후 재시도 + 5회 연속 실패 자동 disable |
| 6 | 2c | `daemon/watchdog.py` + `daemon/transcript.py` (bounded tail) + `commands/cn:dry-run.md` + user_turn log + 알림 | 모든 수동 시나리오 6개 통과 + Net saved 추정 가능 |
| 7 | 3 | `marketplace.json` + README + LICENSE + CHANGELOG | 외부 사용자가 `/plugin install` 한 줄로 설치 후 README만 보고 사용 시작 |

각 PR이 끝나면 사용자 검토 → 승인 → 머지 → 다음 PR 브랜치.

---

# PR 1 (Phase 1a) — 기반 라이브러리

## 목표
세션 ID sanitize / atomic state write / 데몬 lockfile / config 로딩 / logger 라이브러리를 만든다. 플러그인 매니페스트 + 설정 파일 예시도 포함.

## File Structure (PR 1 산출물)

| 파일 | 책임 |
|---|---|
| `.claude-plugin/plugin.json` | 매니페스트 (`name`, `hooks` 경로) |
| `config.toml.example` | 사용자 설정 예시 |
| `lib/__init__.py` | (empty) |
| `lib/session_id.py` | `sanitize(session_id) → sid_hash`, 정규식 통과 시 pass-through, 실패 시 sha256 hash |
| `lib/state.py` | `STATE_LOCK_DEADLINE`, `acquire_state_lock_with_timeout`, `update_state`, `delete_state`, `load_state`, `default_state`, `parse_iso` |
| `lib/lockfile.py` | `proc_start_time`, `is_daemon_alive`, `acquire_daemon_lock` |
| `lib/config.py` | `Config` dataclass + `load_config(path)` |
| `lib/logger.py` | 일자별 회전 로그 (`daemon.log.YYYY-MM-DD`, `fire.log.YYYY-MM-DD`, `user_turn.log.YYYY-MM-DD`) |
| `tests/lib/test_session_id.py` | sanitize 테스트 |
| `tests/lib/test_state.py` | atomic write / lock timeout / 동시성 / allow_create |
| `tests/lib/test_lockfile.py` | normal acquire / stale PID / start_time mismatch |
| `tests/lib/test_config.py` | TOML 파싱 / 기본값 / 누락 키 |
| `tests/conftest.py` | pytest fixtures (tmpdir 기반 STATE_DIR override) |
| `pyproject.toml` 또는 `requirements-dev.txt` | pytest, freezegun |

---

## Task 1.1: 프로젝트 초기 구조 + 매니페스트

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `config.toml.example`
- Create: `pyproject.toml`
- Create: `lib/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/lib/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1.1.1: 매니페스트 작성**

`.claude-plugin/plugin.json`:
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

- [ ] **Step 1.1.2: 설정 파일 예시**

`config.toml.example` — SPEC v5.1의 "설정 파일" 섹션 내용 그대로 복사 (mode/refresh/notify/advanced 4개 섹션).

- [ ] **Step 1.1.3: pyproject.toml + dev dependencies**

```toml
[project]
name = "cache-necromancer"
version = "0.1.0"
requires-python = ">=3.11"

[project.optional-dependencies]
dev = ["pytest>=7", "freezegun>=1.2"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
```

- [ ] **Step 1.1.4: 공통 test fixtures**

`tests/conftest.py`:
```python
import pytest
import os
from pathlib import Path

@pytest.fixture
def cn_root(tmp_path, monkeypatch):
    """임시 ~/.cache-necromancer 디렉토리."""
    root = tmp_path / "cache-necromancer"
    root.mkdir()
    (root / "state").mkdir()
    monkeypatch.setenv("CN_ROOT", str(root))
    return root
```

- [ ] **Step 1.1.5: Commit**

```bash
git add .claude-plugin/ config.toml.example pyproject.toml lib/ tests/
git commit -m "feat: 프로젝트 초기 구조 + plugin 매니페스트 + 설정 예시"
```

---

## Task 1.2: session_id sanitize

**Files:**
- Create: `lib/session_id.py`
- Create: `tests/lib/test_session_id.py`

- [ ] **Step 1.2.1: 실패 테스트 작성**

`tests/lib/test_session_id.py`:
```python
import pytest
from lib.session_id import sanitize

def test_normal_uuid_passthrough():
    sid = "550e8400-e29b-41d4-a716-446655440000"
    assert sanitize(sid) == sid

def test_alphanumeric_passthrough():
    assert sanitize("abc123") == "abc123"

def test_underscore_dash_passthrough():
    assert sanitize("test_session-1") == "test_session-1"

def test_path_traversal_hashed():
    result = sanitize("../etc/passwd")
    assert "/" not in result and ".." not in result
    assert len(result) == 16

def test_special_chars_hashed():
    result = sanitize("session with spaces!")
    assert all(c.isalnum() for c in result)
    assert len(result) == 16

def test_empty_string_raises():
    with pytest.raises(ValueError):
        sanitize("")

def test_too_long_hashed():
    long_id = "a" * 100
    result = sanitize(long_id)
    assert len(result) == 16

def test_deterministic_hash():
    assert sanitize("foo bar") == sanitize("foo bar")

def test_different_inputs_different_hash():
    assert sanitize("foo bar") != sanitize("foo baz")
```

- [ ] **Step 1.2.2: 테스트 실행, 모두 실패 확인**

Run: `pytest tests/lib/test_session_id.py -v`
Expected: 9개 모두 FAIL (`ImportError: cannot import name 'sanitize'`)

- [ ] **Step 1.2.3: 구현**

`lib/session_id.py`:
```python
import hashlib
import re

_VALID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

def sanitize(session_id: str) -> str:
    """session_id를 파일시스템 안전한 sid_hash로 변환.

    정규식 통과 시 그대로 반환. 실패 시 sha256(session_id)[:16].
    빈 문자열은 ValueError.
    """
    if not session_id:
        raise ValueError("session_id must not be empty")
    if _VALID_PATTERN.match(session_id):
        return session_id
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 1.2.4: 테스트 재실행, 모두 통과 확인**

Run: `pytest tests/lib/test_session_id.py -v`
Expected: 9 passed

- [ ] **Step 1.2.5: Commit**

```bash
git add lib/session_id.py tests/lib/test_session_id.py
git commit -m "feat: session_id sanitize (정규식 통과 시 그대로, 실패 시 sha256 hash)"
```

---

## Task 1.3: state.py — atomic write + flock + default_state

**Files:**
- Create: `lib/state.py`
- Create: `tests/lib/test_state.py`

- [ ] **Step 1.3.1: default_state 테스트**

`tests/lib/test_state.py`:
```python
import pytest
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

@pytest.fixture
def state_module(cn_root, monkeypatch):
    """STATE_DIR을 임시 디렉토리로 override."""
    state_dir = cn_root / "state"
    monkeypatch.setattr("lib.state.STATE_DIR", state_dir)
    from lib import state
    return state

def test_default_state_has_all_required_fields(state_module):
    now = datetime.now(timezone.utc)
    s = state_module.default_state(
        session_id="abc",
        sid_hash="abc",
        transcript_path="/tmp/abc.jsonl",
        cwd="/tmp",
        now=now,
    )
    required = {
        "session_id", "sid_hash", "transcript_path", "cwd",
        "last_stop_at", "last_user_input_at", "current_turn_started_at",
        "last_fire_at", "refresh_count", "next_refresh_at",
        "imminent_notified", "consecutive_fire_failures",
        "last_fire_reason", "backoff_until",
        "disabled", "disabled_reason", "disabled_at",
        "cache_cold_retries", "created_at",
    }
    assert required.issubset(s.keys())
    assert s["disabled"] is False
    assert s["refresh_count"] == 0
    assert s["cache_cold_retries"] == 0
```

- [ ] **Step 1.3.2: update_state allow_create 테스트**

```python
def test_update_state_creates_with_allow_create_true(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "session_id": "abc", "refresh_count": 1},
        allow_create=True,
    )
    path = state_module.STATE_DIR / "abc.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["refresh_count"] == 1

def test_update_state_skips_with_allow_create_false_when_missing(state_module):
    state_module.update_state(
        "abc",
        lambda x: {**x, "refresh_count": 1},
        allow_create=False,
    )
    path = state_module.STATE_DIR / "abc.json"
    assert not path.exists()

def test_update_state_mutator_returns_none_aborts_write(state_module):
    # 먼저 파일 생성
    state_module.update_state("abc", lambda x: {**x, "v": 1}, allow_create=True)
    # mutator가 None 반환 → write 안 함
    state_module.update_state("abc", lambda x: None, allow_create=False)
    data = json.loads((state_module.STATE_DIR / "abc.json").read_text())
    assert data["v"] == 1
```

- [ ] **Step 1.3.3: atomic write + lock 테스트**

```python
import threading
import time

def test_atomic_write_no_partial_file_on_concurrent_writes(state_module):
    """동시 쓰기 시 마지막 쓰기가 일관성 있게 보임."""
    errors = []

    def writer(value):
        try:
            for _ in range(50):
                state_module.update_state(
                    "abc",
                    lambda x, v=value: {**x, "value": v, "session_id": "abc"},
                    allow_create=True,
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # 파일이 항상 valid JSON
    data = json.loads((state_module.STATE_DIR / "abc.json").read_text())
    assert "value" in data

def test_lock_timeout_returns_gracefully(state_module, monkeypatch):
    """다른 프로세스가 락 잡고 있으면 deadline 후 timeout 예외."""
    import fcntl
    monkeypatch.setattr(state_module, "STATE_LOCK_DEADLINE", 0.1)

    lock_path = state_module.STATE_DIR / "abc.lock"
    blocker = open(lock_path, "a+")
    fcntl.flock(blocker, fcntl.LOCK_EX)

    # update_state는 timeout 시 silent 리턴 (예외 안 던짐)
    state_module.update_state("abc", lambda x: {**x, "v": 1}, allow_create=True)
    # 파일은 안 만들어짐 (락 못 잡았으므로)
    assert not (state_module.STATE_DIR / "abc.json").exists()

    fcntl.flock(blocker, fcntl.LOCK_UN)
    blocker.close()

def test_corrupt_json_handled_gracefully(state_module):
    """손상된 JSON 파일은 새 데이터로 덮어쓸 수 있다."""
    path = state_module.STATE_DIR / "abc.json"
    path.write_text("{invalid json")
    # corrupt 처리는 호출자가 .corrupt로 백업 + 재생성하는 정책 (logger 영역).
    # update_state 자체는 JSONDecodeError 발생 시 예외 그대로 올린다.
    with pytest.raises(json.JSONDecodeError):
        state_module.update_state("abc", lambda x: {**x, "v": 1}, allow_create=True)

def test_delete_state(state_module):
    state_module.update_state("abc", lambda x: {**x, "v": 1}, allow_create=True)
    assert (state_module.STATE_DIR / "abc.json").exists()
    state_module.delete_state("abc")
    assert not (state_module.STATE_DIR / "abc.json").exists()
```

- [ ] **Step 1.3.4: 테스트 실행, 모두 실패 확인**

Run: `pytest tests/lib/test_state.py -v`
Expected: 모든 테스트 FAIL (ImportError)

- [ ] **Step 1.3.5: state.py 구현**

`lib/state.py` — SPEC v5.1의 "동시성" 섹션 + "default_state" factory 그대로 구현:
```python
import fcntl
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Callable, Optional

STATE_DIR = Path(os.environ.get("CN_ROOT", str(Path.home() / ".cache-necromancer"))) / "state"
STATE_LOCK_DEADLINE = 4.0

class StateLockTimeout(Exception):
    pass

def parse_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None

def default_state(session_id: str, sid_hash: str, transcript_path: str,
                  cwd: str, now: datetime) -> dict:
    return {
        "session_id": session_id,
        "sid_hash": sid_hash,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "last_stop_at": None,
        "last_user_input_at": None,
        "current_turn_started_at": None,
        "last_fire_at": None,
        "refresh_count": 0,
        "next_refresh_at": None,
        "imminent_notified": False,
        "consecutive_fire_failures": 0,
        "last_fire_reason": None,
        "backoff_until": None,
        "disabled": False,
        "disabled_reason": None,
        "disabled_at": None,
        "cache_cold_retries": 0,
        "created_at": now.isoformat(),
    }

def acquire_state_lock_with_timeout(lock_path: Path,
                                     timeout: float = STATE_LOCK_DEADLINE) -> IO:
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

def update_state(sid_hash: str, mutator: Callable[[dict], Optional[dict]],
                 *, allow_create: bool = False) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return  # silent fail (caller가 log 결정)
    try:
        if not path.exists():
            if not allow_create:
                return
            data = {}
        else:
            data = json.loads(path.read_text())
        result = mutator(data)
        if result is None:
            return
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(result, indent=2))
        os.replace(tmp, path)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

def delete_state(sid_hash: str) -> None:
    path = STATE_DIR / f"{sid_hash}.json"
    lock_path = STATE_DIR / f"{sid_hash}.lock"
    try:
        lock_f = acquire_state_lock_with_timeout(lock_path)
    except StateLockTimeout:
        return
    try:
        if path.exists():
            path.unlink()
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

def load_state(sid_hash: str) -> Optional[dict]:
    path = STATE_DIR / f"{sid_hash}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())

def load_all_states() -> list[dict]:
    if not STATE_DIR.exists():
        return []
    out = []
    for p in STATE_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            pass
    return out
```

- [ ] **Step 1.3.6: 테스트 재실행, 모두 통과 확인**

Run: `pytest tests/lib/test_state.py -v`
Expected: all passed

- [ ] **Step 1.3.7: Commit**

```bash
git add lib/state.py tests/lib/test_state.py
git commit -m "feat: state.py — atomic write + flock + default_state factory"
```

---

## Task 1.4: lockfile.py — daemon 단일 인스턴스

**Files:**
- Create: `lib/lockfile.py`
- Create: `tests/lib/test_lockfile.py`

- [ ] **Step 1.4.1: 실패 테스트 작성**

`tests/lib/test_lockfile.py`:
```python
import os
import json
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch

from lib.lockfile import (
    proc_start_time, is_daemon_alive, acquire_daemon_lock,
)

def test_proc_start_time_self():
    """현재 프로세스의 start_time을 반환."""
    s = proc_start_time(os.getpid())
    assert s is not None and len(s) > 0

def test_proc_start_time_dead_process():
    """존재하지 않는 PID는 None."""
    assert proc_start_time(999999) is None

def test_is_daemon_alive_missing_file(tmp_path):
    assert is_daemon_alive(tmp_path / "missing.lock") is False

def test_is_daemon_alive_empty_file(tmp_path):
    p = tmp_path / "empty.lock"
    p.touch()
    assert is_daemon_alive(p) is False

def test_is_daemon_alive_valid_self(tmp_path):
    """현재 프로세스의 PID + start_time을 기록한 파일은 alive."""
    p = tmp_path / "self.lock"
    pid = os.getpid()
    p.write_text(json.dumps({
        "pid": pid,
        "started": proc_start_time(pid),
    }))
    assert is_daemon_alive(p) is True

def test_is_daemon_alive_pid_reuse_mismatch(tmp_path):
    """동일 PID이지만 start_time이 다르면 stale."""
    p = tmp_path / "stale.lock"
    p.write_text(json.dumps({
        "pid": os.getpid(),
        "started": "Fri Jan  1 00:00:00 1970",
    }))
    assert is_daemon_alive(p) is False

def test_acquire_daemon_lock_success(tmp_path):
    f = acquire_daemon_lock(tmp_path / "d.lock")
    assert f is not None
    f.close()

def test_acquire_daemon_lock_blocks_second_acquire(tmp_path):
    p = tmp_path / "d.lock"
    f1 = acquire_daemon_lock(p)
    assert f1 is not None
    f2 = acquire_daemon_lock(p)
    assert f2 is None  # 이미 alive
    f1.close()
```

- [ ] **Step 1.4.2: 테스트 실행, 모두 실패 확인**

Run: `pytest tests/lib/test_lockfile.py -v`
Expected: ImportError

- [ ] **Step 1.4.3: lockfile.py 구현**

SPEC v5.1의 "데몬 lifecycle" 섹션 그대로 구현. `proc_start_time` + `is_daemon_alive` + `acquire_daemon_lock`. (코드는 SPEC 참조)

- [ ] **Step 1.4.4: 테스트 재실행, 모두 통과 확인**

Run: `pytest tests/lib/test_lockfile.py -v`
Expected: all passed

- [ ] **Step 1.4.5: Commit**

```bash
git add lib/lockfile.py tests/lib/test_lockfile.py
git commit -m "feat: daemon lockfile (PID + start_time으로 단일 인스턴스 보장)"
```

---

## Task 1.5: config.py — TOML 로드

**Files:**
- Create: `lib/config.py`
- Create: `tests/lib/test_config.py`

- [ ] **Step 1.5.1: 실패 테스트 작성**

`tests/lib/test_config.py`:
```python
import pytest
from pathlib import Path
from lib.config import load_config, Config

def test_load_defaults_when_file_missing(tmp_path):
    """존재하지 않는 path → 기본값 반환."""
    c = load_config(tmp_path / "nonexistent.toml")
    assert c.mode == "hybrid"
    assert c.refresh_interval_minutes == 55
    assert c.max_refresh_count == 10
    assert c.refresh.prompt == "."
    assert c.refresh.hybrid_wait_seconds == 60
    assert c.advanced.daemon_poll_max_seconds == 60
    assert c.advanced.cache_cold_max_retries == 2

def test_load_partial_overrides(tmp_path):
    """일부 키만 있어도 나머지는 기본값."""
    p = tmp_path / "c.toml"
    p.write_text("[general]\nmode = \"auto\"\nmax_refresh_count = 20\n")
    c = load_config(p)
    assert c.mode == "auto"
    assert c.max_refresh_count == 20
    assert c.refresh_interval_minutes == 55  # default 유지

def test_load_full_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[general]
mode = "notify"
refresh_interval_minutes = 30
max_refresh_count = 5

[refresh]
prompt = "ping"
hybrid_wait_seconds = 90
fire_timeout_seconds = 60

[notify]
terminal_bell = false

[advanced]
daemon_poll_max_seconds = 30
""")
    c = load_config(p)
    assert c.mode == "notify"
    assert c.refresh_interval_minutes == 30
    assert c.refresh.prompt == "ping"
    assert c.notify.terminal_bell is False

def test_invalid_mode_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[general]\nmode = \"invalid\"\n")
    with pytest.raises(ValueError, match="mode"):
        load_config(p)
```

- [ ] **Step 1.5.2: 테스트 실행, 모두 실패 확인**

Run: `pytest tests/lib/test_config.py -v`

- [ ] **Step 1.5.3: config.py 구현**

`lib/config.py`:
```python
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VALID_MODES = ("notify", "auto", "hybrid")

@dataclass
class RefreshConfig:
    prompt: str = "."
    hybrid_wait_seconds: int = 60
    fire_timeout_seconds: int = 120

@dataclass
class NotifyConfig:
    terminal_bell: bool = True
    system_notification: bool = True
    imminent_threshold_minutes: int = 5

@dataclass
class AdvancedConfig:
    daemon_poll_max_seconds: int = 60
    session_ttl_hours: int = 24
    daemon_idle_shutdown_minutes: int = 60
    clock_drift_threshold_seconds: int = 30
    clock_drift_postpone_minutes: int = 5
    fire_stop_watchdog_seconds: int = 120
    consecutive_fire_failures_disable: int = 5
    cache_cold_max_retries: int = 2
    backoff_base_seconds: float = 30.0
    backoff_cap_seconds: float = 1800.0
    interactive_input_quiet_seconds: int = 30
    state_lock_deadline_seconds: float = 4.0

@dataclass
class Config:
    mode: Literal["notify", "auto", "hybrid"] = "hybrid"
    refresh_interval_minutes: int = 55
    max_refresh_count: int = 10
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)

def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    general = data.get("general", {})
    mode = general.get("mode", "hybrid")
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode}. Must be one of {VALID_MODES}")
    return Config(
        mode=mode,
        refresh_interval_minutes=general.get("refresh_interval_minutes", 55),
        max_refresh_count=general.get("max_refresh_count", 10),
        refresh=RefreshConfig(**data.get("refresh", {})),
        notify=NotifyConfig(**data.get("notify", {})),
        advanced=AdvancedConfig(**data.get("advanced", {})),
    )
```

- [ ] **Step 1.5.4: 테스트 통과 확인**

Run: `pytest tests/lib/test_config.py -v`

- [ ] **Step 1.5.5: Commit**

```bash
git add lib/config.py tests/lib/test_config.py
git commit -m "feat: config.py (TOML 로드 + 기본값 + mode 검증)"
```

---

## Task 1.6: logger.py — 일자별 회전 로그

**Files:**
- Create: `lib/logger.py`
- Create: `tests/lib/test_logger.py`

- [ ] **Step 1.6.1: 실패 테스트 작성**

```python
def test_logger_writes_dated_file(cn_root, monkeypatch):
    monkeypatch.setattr("lib.logger.LOG_DIR", cn_root)
    from lib.logger import log_info, log_warn
    log_info("test message")
    # 오늘 날짜 daemon.log.YYYY-MM-DD
    from datetime import date
    today = date.today().isoformat()
    p = cn_root / f"daemon.log.{today}"
    assert p.exists()
    assert "test message" in p.read_text()

def test_log_fire_writes_to_fire_log(cn_root, monkeypatch):
    monkeypatch.setattr("lib.logger.LOG_DIR", cn_root)
    from lib.logger import log_fire
    from datetime import datetime, timezone
    log_fire(
        sid_hash="abc", session_id="abc123",
        model="opus-4-7", reason="ok",
        cache_read=45844, cache_create=271,
        input_tokens=6, output_tokens=253,
        now=datetime.now(timezone.utc),
    )
    from datetime import date
    p = cn_root / f"fire.log.{date.today().isoformat()}"
    assert p.exists()
    line = p.read_text().strip()
    assert "sid=abc" in line
    assert "cache_read=45844" in line
    assert "reason=ok" in line

def test_logs_no_sensitive_data(cn_root, monkeypatch):
    monkeypatch.setattr("lib.logger.LOG_DIR", cn_root)
    from lib.logger import log_fire
    from datetime import datetime, timezone
    log_fire(
        sid_hash="abc", session_id="abc123",
        model="opus-4-7", reason="ok",
        cache_read=100, cache_create=0,
        input_tokens=5, output_tokens=10,
        now=datetime.now(timezone.utc),
    )
    from datetime import date
    line = (cn_root / f"fire.log.{date.today().isoformat()}").read_text()
    # 프롬프트 / cwd / 경로 절대 포함 안 됨
    assert "cwd" not in line.lower()
    assert "prompt" not in line.lower()
```

- [ ] **Step 1.6.2: logger.py 구현**

`lib/logger.py`:
```python
import os
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

LOG_DIR = Path(os.environ.get("CN_ROOT", str(Path.home() / ".cache-necromancer")))

def _today_suffix() -> str:
    return date.today().isoformat()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _append(filename_prefix: str, line: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{filename_prefix}.{_today_suffix()}"
    with open(path, "a") as f:
        f.write(line + "\n")

def log_info(msg: str) -> None:
    _append("daemon.log", f"{_now_iso()} INFO  {msg}")

def log_warn(msg: str) -> None:
    _append("daemon.log", f"{_now_iso()} WARN  {msg}")

def log_fire(sid_hash: str, session_id: Optional[str], model: Optional[str],
             reason: str, cache_read: int, cache_create: int,
             input_tokens: int, output_tokens: int, now: datetime) -> None:
    """fire 결과 raw log. 민감정보 미기록 (sid_hash + 토큰 수 + model + reason만)."""
    line = (f"{now.isoformat()} | fire | sid={sid_hash} | model={model} | "
            f"reason={reason} | cache_read={cache_read} | "
            f"cache_create={cache_create} | input={input_tokens} | "
            f"output={output_tokens}")
    _append("fire.log", line)

def log_user_turn(sid_hash: str, session_id: Optional[str], usage: dict,
                  after_fire: bool, now: datetime) -> None:
    line = (f"{now.isoformat()} | user_turn | sid={sid_hash} | "
            f"model={usage.get('model', 'unknown')} | "
            f"cache_read={usage.get('cache_read_input_tokens', 0)} | "
            f"cache_create={usage.get('cache_creation_input_tokens', 0)} | "
            f"input={usage.get('input_tokens', 0)} | "
            f"output={usage.get('output_tokens', 0)} | "
            f"after_fire={'true' if after_fire else 'false'}")
    _append("user_turn.log", line)
```

7일 후 자동 삭제 로직은 Phase 4로 미룸 (v1은 사용자가 수동 삭제 OK, 문서로 안내).

- [ ] **Step 1.6.3: 테스트 통과 확인**

- [ ] **Step 1.6.4: Commit**

```bash
git add lib/logger.py tests/lib/test_logger.py
git commit -m "feat: logger (일자별 회전 + 민감정보 미기록)"
```

---

## Task 1.7: PR 1 마무리 + PR 생성

- [ ] **Step 1.7.1: 전체 테스트 통과 확인**

Run: `pytest tests/lib/ -v`
Expected: 모든 단위 테스트 통과

- [ ] **Step 1.7.2: 코드리뷰 (서브에이전트 병렬 실행)**

CLAUDE.md 코드리뷰 룰 따라 7개 에이전트 병렬:
- 아키텍처 / 원칙 준수 / 중복-복잡도 / 사이드이펙트-에러 / 보안 / 성능 / 테스트 커버리지

CRITICAL 0건일 때만 다음 단계. 사용자에게 결과 보고.

- [ ] **Step 1.7.3: 사용자 승인 받기**

리뷰 결과 + 코드 변경 요약 사용자에게 보고. 승인 받은 후 진행.

- [ ] **Step 1.7.4: PR 생성**

```bash
git push -u origin feature/phase-1a-lib-foundation
gh pr create --title "feat(phase-1a): 기반 라이브러리 (state/lockfile/session_id/config/logger)" --body "$(cat <<'EOF'
## Summary
- session_id sanitize (정규식 + sha256 fallback)
- state.py atomic write + flock + default_state factory
- lockfile.py 단일 데몬 보장 (PID + start_time)
- config.py TOML 로드 + 기본값
- logger.py 일자별 회전 + 민감정보 미기록

PRD: docs/superpowers/specs/2026-05-12-cache-necromancer-PRD.md
SPEC v5.1: docs/superpowers/specs/2026-05-12-cache-necromancer-design-v5.md

## Test plan
- [x] pytest tests/lib/ 모두 통과
- [x] 동시 쓰기 / stale PID / 손상 JSON / lock timeout 시나리오 검증

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 1.7.5: 사용자 머지 승인 대기**

CLAUDE.md 룰: 머지는 반드시 사용자가 명시적으로 "머지해"라고 지시할 때만.

---

# PR 2 (Phase 1b) — Hook + 데몬 골격 + notify 모드 (outline)

**Goal**: 실제 Claude Code에서 Stop hook이 발사되면 state 갱신 + 데몬 lazy spawn + 55분 후 macOS 알림.

**Tasks (PR 2 시작 시 상세화)**:
- `hooks/hooks.json` 작성 (Stop / UserPromptSubmit / SessionEnd 등록)
- `scripts/on_stop.py` — stdin JSON 읽기 + `default_state` + transcript bounded tail (Phase 2c로 미룰 수 있음, 일단 stub) + `update_state` + spawn_daemon
- `scripts/on_user_prompt.py` — `last_user_input_at` / `current_turn_started_at` 갱신 (allow_create=False)
- `scripts/on_session_end.py` — `delete_state`
- `daemon/notifier.py` — `osascript`로 macOS 알림 + 터미널 벨 + tests (mock)
- `daemon/clock.py` — `DriftDetector` + tests
- `daemon/poller.py` — `notify` 모드만, `is_refresh_candidate` (disabled / backoff_until / interactive quiet 가드 포함)
- `daemon/__main__.py` — `acquire_daemon_lock` + `run_poll_loop`

**검증 기준**:
- 실제 Claude Code 세션에서 응답 후 state JSON 생성 확인
- 55분 강제 단축 (config 임시 조정)으로 macOS 알림 발생 확인
- 데몬 idle 셧다운 확인 (모든 세션 1h stale)
- 단위 테스트 + 통합 테스트 통과

**PR 시작 시점에 상세 task를 PLAN에 추가**.

---

# PR 3 (Phase 1c) — `/cn:status` 명령 (outline)

**Goal**: 사용자가 `/cn:status` 호출 시 데몬 상태 + 추적 세션 + disabled 세션 확인.

**Tasks**:
- `commands/cn:status.md` (frontmatter + Bash 실행)
- `scripts/cn_status.py` — `os.environ.get("CLAUDE_CODE_SESSION_ID")`로 현재 세션 마킹 + `load_all_states` + 출력 포맷
- 24h fire.log 통계 (success/cache_cold/network_error 카운트)

**검증 기준**: SPEC v5.1의 `/cn:status` 출력 예시와 일치.

---

# PR 4 (Phase 2a) — fire 호출 + FireReason 분기 (outline)

**Goal**: `daemon/refresh.py`로 `claude -p` 헤드레스 호출 + JSON 응답 파싱 + `FireReason` 7종 분기.

**Tasks**:
- `FireReason` enum + `FireResult` dataclass + `TRANSIENT_REASONS` / `PERMANENT_REASONS` / `AUTH_ERROR_PATTERNS`
- `fire(state, config)` — `subprocess.run(claude -p ...)` + JSON 파싱 + `FireReason` 분기 (CACHE_COLD / NETWORK_ERROR / AUTH_ERROR / TIMEOUT / PROCESS_ERROR / BAD_OUTPUT / OK)
- `disable_session()` 헬퍼 (delete 대신 disabled 마커)
- subprocess.run mock 단위 테스트 + 실제 `claude -p hi` 통합 테스트 (CI 최소 비용)

**검증 기준**:
- 단위 테스트: 모든 FireReason 분기 통과
- 통합 테스트: 실제 cache_read 측정 (실험과 동일한 결과)

---

# PR 5 (Phase 2b) — auto/hybrid + 스케줄러 + backoff (outline)

**Goal**: `handle_fire_result`로 성공 시 next_refresh_at 직접 갱신 + 실패 시 backoff + 5회 연속 disable.

**Tasks**:
- `handle_fire_result(s, result, config)` (성공 / PERMANENT / CACHE_COLD / TRANSIENT 분기)
- `_backoff_seconds(failure_count, base, cap)` — exponential + jitter
- `INTERACTIVE_INPUT_QUIET_SECONDS=30` 가드
- `is_refresh_candidate` 확장 (disabled / backoff_until / current_turn_started_at / interactive quiet)
- `execute_mode` (notify / auto / hybrid 분기)
- `sleep_with_cancel` (hybrid)

**검증 기준**:
- 자동 fire 발생 후 next_refresh_at 자동 갱신
- 실패 시 backoff 후 재시도
- 5회 연속 실패 시 disabled

---

# PR 6 (Phase 2c) — watchdog + transcript bounded tail + user_turn log + `/cn:dry-run` (outline)

**Goal**: 예외 복구 watchdog + transcript jsonl 마지막 turn usage 추출 (≤100ms) + user_turn log + dry-run 명령.

**Tasks**:
- `daemon/watchdog.py` — `watchdog_check(s, now, config)` (예외 복구 전용)
- `daemon/transcript.py` — `_read_tail(64KB)` + `extract_last_turn_usage` (bounded, deadline 추가)
- Stop hook이 `extract_last_turn_usage` 호출해서 user_turn log 기록
- `commands/cn:dry-run.md` + `scripts/cn_dry_run.py`
- 연속 실패 알림 (3회) + AUTH_ERROR 즉시 알림

**검증 기준**:
- transcript 64KB 이내에서 마지막 assistant usage 추출
- watchdog 120s 후 복구
- 수동 시나리오 6개 (PRD v3) 모두 통과
- log에서 Net saved 추정 가능 (after_fire 판정 정확)

---

# PR 7 (Phase 3) — 공개 배포 준비 (outline)

**Goal**: `/plugin install` 한 줄로 외부 사용자가 설치 + 안전하게 사용 시작.

**Tasks**:
- `.claude-plugin/marketplace.json` (등록 정보)
- README.md (설치 / 추천·비추천 사용 패턴 / 안전성 확인 / 트러블슈팅)
- LICENSE (MIT)
- CHANGELOG.md
- `userConfig` 활용한 첫 설치 시 모드 안내 (선택)

**검증 기준**:
- 외부 사용자가 빈 디렉토리에서 `/plugin install cache-necromancer` 한 줄로 설치 후 README만 보고 사용 시작
- `/cn:status`로 추적 확인

---

## 자체 리뷰 (PLAN 작성 후 self-check)

- [x] **Spec coverage**: PRD v3의 모든 유저 스토리 / 시나리오 / 안전 보장 12가지 / Phase 1+2+3 deliverable이 PR 1~7에 매핑됨.
- [x] **Placeholder scan**: TBD / TODO / "implement later" 없음. 각 task는 실제 코드 or SPEC 참조.
- [x] **Type consistency**: `sid_hash` / `default_state` / `FireResult` / `FireReason` 등 타입명이 모든 task에서 일관.
- [x] **PR 독립성**: PR 1 (lib) → PR 2 (hook + daemon notify) → PR 3 (status) → PR 4 (fire) → PR 5 (auto/hybrid) → PR 6 (watchdog + transcript) → PR 7 (배포). 의존 방향 단방향.

**알려진 한계**: PR 2~7은 outline 수준. 각 PR 시작 시 그 PR의 상세 step-by-step task를 이 PLAN에 추가하거나 별도 PR-specific PLAN을 만든다. 이렇게 하는 이유는 (1) 사용자 검토 부담 최소화, (2) 각 PR이 작아서 시작 시 컨텍스트 새로 정리하면 더 정확함.

---

## 사용자 검토 체크리스트

PLAN OK 하실 때 다음 항목 확인:

1. **PR 분해 7개**가 합리적인가? 더 잘게 / 합쳐야 할 부분 있는가?
2. **PR 1 (Phase 1a)의 상세 task 7개**가 적절한가? (1.1 매니페스트 → 1.2 session_id → 1.3 state → 1.4 lockfile → 1.5 config → 1.6 logger → 1.7 PR 생성)
3. **TDD 사이클 (test 먼저 → 실패 확인 → 구현 → 통과 → commit)** 그대로 진행 OK?
4. **PR 2~7 outline 수준 + 시작 시 상세화** 방식 OK?
5. **각 PR 끝나면 코드리뷰 7개 에이전트 병렬 + 사용자 승인 + 머지** — CLAUDE.md 룰 그대로?

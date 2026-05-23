# Cache Recap Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop hook fire 즉시 사용자에게 "다음 wake 시각" 을 `systemMessage` 로 표시 (Claude Code recap 영역).

**Architecture:** Stop 배열에 hook 객체 2개 등록 — sync hook (`on_recap.py`, 신규) 가 먼저 stdout JSON 출력, 그 다음 기존 async hook (`refresh.py`) 가 background sleep+wake. asyncRewake true 모드의 stdout 캡처 타이밍 불확정 이슈를 hook 분리로 우회.

**Tech Stack:** Python 3.11+, Claude Code hooks JSON spec, pytest, `lib/config.py` / `lib/marker.py` / `lib/notify.py` / `lib/logger.py` (기존 그대로 import).

**Spec:** `docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md`

---

## File Structure

### 신규
- `scripts/on_recap.py` — sync Stop hook 본체 (systemMessage 출력)
- `tests/scripts/test_on_recap.py` — pytest 케이스 (19개)

### 수정
- `hooks/hooks.json` — Stop 배열에 sync hook 추가

### 변경 없음 (회귀 테스트로 보호)
- `scripts/refresh.py` — 기존 PING / wake 로직
- `lib/*` — config, marker, notify, logger
- 기타 scripts/

---

## Task 1: hooks.json — sync hook 추가

**Files:**
- Modify: `hooks/hooks.json`
- Test: `tests/scripts/test_on_recap.py` (신규, hook 구조 검증부터 시작)

- [ ] **Step 1: 테스트 파일 신규 + hook 구조 검증 테스트 작성**

`tests/scripts/test_on_recap.py` (신규 파일):

```python
"""Tests for scripts/on_recap.py + hooks/hooks.json 구조 (recap design spec)."""
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_hooks_json() -> dict:
    path = _PROJECT_ROOT / "hooks" / "hooks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_hooks_json_stop_array_has_two_entries():
    """Stop 배열에 sync (on_recap) + async (refresh) 두 hook 등록."""
    data = _load_hooks_json()
    stop = data["hooks"]["Stop"]
    assert len(stop) == 2, f"Stop 배열 객체 2개 기대, 실제 {len(stop)}"


def test_hooks_json_first_stop_is_sync_recap():
    """첫번째 = on_recap.py (sync, asyncRewake X, timeout 5)."""
    data = _load_hooks_json()
    first = data["hooks"]["Stop"][0]["hooks"][0]
    assert "on_recap.py" in first["command"]
    assert first.get("asyncRewake") is not True
    assert first["timeout"] == 5


def test_hooks_json_second_stop_is_async_refresh_unchanged():
    """두번째 = refresh.py (asyncRewake true, timeout 3600) — 기존 그대로."""
    data = _load_hooks_json()
    second = data["hooks"]["Stop"][1]["hooks"][0]
    assert "refresh.py" in second["command"]
    assert second["asyncRewake"] is True
    assert second["timeout"] == 3600
```

- [ ] **Step 2: 테스트 실행 → FAIL 확인**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 3 FAIL (Stop 배열 길이 1, on_recap.py 없음)

- [ ] **Step 3: hooks.json 에 sync hook 추가**

기존 `hooks/hooks.json` 의 `Stop` 배열 값을 다음으로 교체:

```json
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/on_recap.py\"",
            "timeout": 5
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/refresh.py\"",
            "asyncRewake": true,
            "timeout": 3600
          }
        ]
      }
    ],
```

- [ ] **Step 4: 테스트 실행 → PASS 확인**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 3 PASS

- [ ] **Step 5: commit**

```bash
git add hooks/hooks.json tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): hooks.json 에 sync recap hook 등록"
```

---

## Task 2: on_recap.py — entry + silent fail wrap

**Files:**
- Create: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: 테스트 추가 (silent fail entry)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
import io
from unittest.mock import patch

import pytest


@pytest.fixture
def session_stdin(monkeypatch):
    """stdin JSON 으로 session_id 주입."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sid = "test-recap-sid"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    return sid


@pytest.fixture
def empty_stdin(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def test_main_no_session_id_exits_silently(empty_stdin, capsys):
    """session_id 없으면 stdout empty + exit 0."""
    from scripts.on_recap import main
    rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_main_top_level_exception_silent_fail(session_stdin, capsys, monkeypatch):
    """예상 밖 예외 발생해도 stdout empty + exit 0."""
    def boom(_):
        raise RuntimeError("boom")
    monkeypatch.setattr("scripts.on_recap.sanitize", boom)
    from scripts.on_recap import main
    rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
```

- [ ] **Step 2: 테스트 실행 → FAIL (`scripts.on_recap` 모듈 없음)**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 2 새 테스트 FAIL with ImportError

- [ ] **Step 3: on_recap.py 골격 작성**

`scripts/on_recap.py` (신규):

```python
#!/usr/bin/env python3
"""Stop hook 의 sync 본체 — recap 영역에 다음 wake 시각 표시.

design spec: docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md
PRD 불변: 어떤 실패도 chat 동작 차단 X (silent fail).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import ensure_config_file, load_config  # noqa: E402
from lib.logger import log_warn  # noqa: E402
from lib.marker import Marker  # noqa: E402
from lib.session_id import sanitize  # noqa: E402

_KST = timezone(timedelta(hours=9))


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _resolve_session_id() -> str:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            sid = data.get("session_id", "")
            if sid:
                return sid
    except (json.JSONDecodeError, OSError):
        pass
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def _main_impl() -> int:
    sid = _resolve_session_id()
    if not sid:
        return 0
    sanitize(sid)  # 다음 task 에서 실제 사용
    return 0


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] 예외 silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 5 PASS (3 hook 구조 + 2 silent fail)

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): on_recap.py 골격 + silent fail wrap"
```

---

## Task 3: HH:MM 계산 (KST) + 정상 auto mode 메시지

**Files:**
- Modify: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: 테스트 추가 (정상 case + 자정 넘김)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
@pytest.fixture
def temp_root(monkeypatch, tmp_path):
    """CN_ROOT 를 tmp_path 로 격리. config.toml 자동 생성됨."""
    monkeypatch.setenv("CN_ROOT", str(tmp_path))
    return tmp_path


def _freeze_kst(monkeypatch, hh: int, mm: int):
    """datetime.now(_KST) 를 고정. timedelta 연산 유지."""
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    frozen = datetime(2026, 5, 23, hh, mm, 0, tzinfo=kst)

    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr("scripts.on_recap.datetime", _FixedDT)


def test_auto_mode_normal_message(session_stdin, temp_root, capsys, monkeypatch):
    """auto mode + interval=50, fire=10:00 → '🪦 캐시는 10:50 KST 에 살리러 갈게요!'"""
    _freeze_kst(monkeypatch, 10, 0)
    # config.toml 작성 (auto mode, interval 50)
    (temp_root / "config.toml").write_text(
        'mode = "auto"\nrefresh_interval_minutes = 50\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["systemMessage"] == "🪦 캐시는 10:50 KST 에 살리러 갈게요!"


def test_midnight_rollover(session_stdin, temp_root, capsys, monkeypatch):
    """fire=23:55, interval=30 → '00:25 KST'"""
    _freeze_kst(monkeypatch, 23, 55)
    (temp_root / "config.toml").write_text(
        'mode = "auto"\nrefresh_interval_minutes = 30\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "00:25 KST" in out["systemMessage"]
```

- [ ] **Step 2: 테스트 실행 → FAIL (메시지 안 나옴)**

Run: `uv run pytest tests/scripts/test_on_recap.py::test_auto_mode_normal_message tests/scripts/test_on_recap.py::test_midnight_rollover -v`
Expected: 2 FAIL with KeyError (stdout empty)

- [ ] **Step 3: on_recap.py 에 HH:MM 계산 + auto mode 메시지 추가**

`scripts/on_recap.py` 의 `_main_impl` 함수 본문 교체:

```python
def _build_message_auto_hybrid(death_hhmm: str) -> str:
    return f"🪦 캐시는 {death_hhmm} KST 에 살리러 갈게요!"


def _main_impl() -> int:
    sid = _resolve_session_id()
    if not sid:
        return 0
    try:
        sanitize(sid)
    except ValueError:
        return 0

    config_path = _resolve_root() / "config.toml"
    try:
        ensure_config_file(config_path)
        config = load_config(config_path)
    except (OSError, ValueError):
        return 0

    interval = config.refresh_interval_minutes
    death_at = datetime.now(_KST) + timedelta(minutes=interval)
    death_hhmm = death_at.strftime("%H:%M")

    message = _build_message_auto_hybrid(death_hhmm)
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 7 PASS

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): HH:MM KST 계산 + auto mode 메시지"
```

---

## Task 4: hybrid mode + notify mode 분기

**Files:**
- Modify: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: 테스트 추가 (hybrid + notify true/false)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
def test_hybrid_mode_same_as_auto(session_stdin, temp_root, capsys, monkeypatch):
    _freeze_kst(monkeypatch, 12, 30)
    (temp_root / "config.toml").write_text(
        'mode = "hybrid"\nrefresh_interval_minutes = 50\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 캐시는 13:20 KST 에 살리러 갈게요!"


def test_notify_mode_with_system_notification_true(session_stdin, temp_root, capsys, monkeypatch):
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "notify"\nrefresh_interval_minutes = 50\n\n[notify]\nsystem_notification = true\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "10:50 KST" in out["systemMessage"]
    assert "알림만 갑니다" in out["systemMessage"]
    assert "직접 돌아오세요" in out["systemMessage"]


def test_notify_mode_with_system_notification_false(session_stdin, temp_root, capsys, monkeypatch):
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "notify"\nrefresh_interval_minutes = 50\n\n[notify]\nsystem_notification = false\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "10:50 KST" in out["systemMessage"]
    assert "자동 wake/알림 없음" in out["systemMessage"]
    assert "직접 재진입 필요" in out["systemMessage"]
```

- [ ] **Step 2: 테스트 실행 → FAIL (notify 메시지 미구현)**

Run: `uv run pytest tests/scripts/test_on_recap.py::test_notify_mode_with_system_notification_true -v`
Expected: FAIL ("알림만 갑니다" not in message — 현재 auto 메시지 출력)

- [ ] **Step 3: on_recap.py 에 mode 분기 추가**

`scripts/on_recap.py` 에 메시지 빌더 함수 교체 + `_main_impl` 의 message 라인 교체:

```python
def _build_message(
    death_hhmm: str,
    mode: str,
    system_notification: bool,
) -> str:
    """mode + system_notification 조합으로 정확한 메시지 생성."""
    if mode == "notify":
        if system_notification:
            return (
                f"🪦 캐시는 {death_hhmm} KST 에 만료 임박, "
                "알림만 갑니다. 직접 돌아오세요."
            )
        return (
            f"🪦 캐시는 {death_hhmm} KST 에 만료 임박. "
            "자동 wake/알림 없음 — 직접 재진입 필요."
        )
    # auto / hybrid
    return f"🪦 캐시는 {death_hhmm} KST 에 살리러 갈게요!"
```

그리고 `_main_impl` 의 message 라인을 다음으로 교체:

```python
    message = _build_message(
        death_hhmm,
        config.mode,
        config.notify.system_notification,
    )
```

기존 `_build_message_auto_hybrid` 함수 삭제.

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 10 PASS

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): mode 별 메시지 분기 (auto/hybrid/notify)"
```

---

## Task 5: max_refresh_count 도달 분기

**Files:**
- Modify: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: 테스트 추가 (max_count 도달)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
def _write_marker(temp_root, sid: str, wake_count: int):
    """marker 파일 직접 작성. sid_hash 는 sanitize 결과 사용."""
    from lib.session_id import sanitize
    sid_hash = sanitize(sid)
    marker_dir = temp_root / "marker"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{sid_hash}.json").write_text(
        json.dumps({"latest_fire": 0, "wake_count": wake_count, "last_wake_at": 0}),
        encoding="utf-8",
    )


def test_max_count_reached_auto_mode(session_stdin, temp_root, capsys, monkeypatch):
    """auto mode + wake_count=10, max=10 → 한도 도달 메시지."""
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "auto"\nrefresh_interval_minutes = 50\nmax_refresh_count = 10\n',
        encoding="utf-8",
    )
    _write_marker(temp_root, session_stdin, wake_count=10)
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "10:50 KST" in out["systemMessage"]
    assert "자동 살림 한도 도달" in out["systemMessage"]
    assert "직접 메시지를 보내세요" in out["systemMessage"]


def test_max_count_reached_notify_mode_same_message(session_stdin, temp_root, capsys, monkeypatch):
    """notify mode 라도 max_count 도달 시 같은 메시지 (mode 무관)."""
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "notify"\nrefresh_interval_minutes = 50\nmax_refresh_count = 10\n',
        encoding="utf-8",
    )
    _write_marker(temp_root, session_stdin, wake_count=10)
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "자동 살림 한도 도달" in out["systemMessage"]
```

- [ ] **Step 2: 테스트 실행 → FAIL (한도 메시지 미구현)**

Run: `uv run pytest tests/scripts/test_on_recap.py::test_max_count_reached_auto_mode -v`
Expected: FAIL ("자동 살림 한도 도달" not in message)

- [ ] **Step 3: on_recap.py 에 maxed_out 분기 추가**

`scripts/on_recap.py` 의 `_build_message` 함수 본문 교체:

```python
def _build_message(
    death_hhmm: str,
    mode: str,
    system_notification: bool,
    maxed_out: bool,
) -> str:
    """mode + max_count 분기로 정확한 메시지 생성."""
    if maxed_out:
        return (
            f"🪦 캐시는 {death_hhmm} KST 에 만료 임박. "
            "자동 살림 한도 도달 — 유지하려면 직접 메시지를 보내세요."
        )
    if mode == "notify":
        if system_notification:
            return (
                f"🪦 캐시는 {death_hhmm} KST 에 만료 임박, "
                "알림만 갑니다. 직접 돌아오세요."
            )
        return (
            f"🪦 캐시는 {death_hhmm} KST 에 만료 임박. "
            "자동 wake/알림 없음 — 직접 재진입 필요."
        )
    return f"🪦 캐시는 {death_hhmm} KST 에 살리러 갈게요!"
```

그리고 `_main_impl` 에 marker load + 호출 인자 추가. `_main_impl` 의 message 빌더 호출 부분을 다음으로 교체:

```python
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0
    # ... config 로드 후 ...

    try:
        marker = Marker.load(sid_hash)
        maxed_out = marker.wake_count >= config.max_refresh_count
    except OSError:
        maxed_out = False

    message = _build_message(
        death_hhmm,
        config.mode,
        config.notify.system_notification,
        maxed_out,
    )
```

`_main_impl` 전체 최종 형태:

```python
def _main_impl() -> int:
    sid = _resolve_session_id()
    if not sid:
        return 0
    try:
        sid_hash = sanitize(sid)
    except ValueError:
        return 0

    config_path = _resolve_root() / "config.toml"
    try:
        ensure_config_file(config_path)
        config = load_config(config_path)
    except (OSError, ValueError):
        return 0

    interval = config.refresh_interval_minutes
    death_at = datetime.now(_KST) + timedelta(minutes=interval)
    death_hhmm = death_at.strftime("%H:%M")

    try:
        marker = Marker.load(sid_hash)
        maxed_out = marker.wake_count >= config.max_refresh_count
    except OSError:
        maxed_out = False

    message = _build_message(
        death_hhmm,
        config.mode,
        config.notify.system_notification,
        maxed_out,
    )
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 12 PASS

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): max_refresh_count 도달 시 메시지 분기"
```

---

## Task 6: interval 가드 (isinstance + > 0)

**Files:**
- Modify: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: 테스트 추가 (interval 0/음수/문자열)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
@pytest.mark.parametrize("interval", [0, -1, -100])
def test_invalid_interval_silent_fail(
    session_stdin, temp_root, capsys, monkeypatch, interval
):
    """interval <= 0 → stdout empty + exit 0."""
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        f'mode = "auto"\nrefresh_interval_minutes = {interval}\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_interval_non_int_silent_fail(
    session_stdin, temp_root, capsys, monkeypatch
):
    """interval 이 문자열 (TOML schema 위반) → silent fail.

    load_config 가 ValueError 던질 가능성 → silent fail 경로로도 OK.
    던지지 않고 str 반환하면 on_recap 의 isinstance 가드가 잡아야 함.
    """
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "auto"\nrefresh_interval_minutes = "abc"\n', encoding="utf-8"
    )
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: 테스트 실행 → FAIL 또는 ERROR (현재 가드 X)**

Run: `uv run pytest tests/scripts/test_on_recap.py::test_invalid_interval_silent_fail -v`
Expected: FAIL — interval=0 일 때 메시지 출력됨, 음수면 과거 시각 출력됨

- [ ] **Step 3: on_recap.py 에 isinstance + > 0 가드 추가**

`scripts/on_recap.py` 의 `_main_impl` 함수 내부 `interval = config.refresh_interval_minutes` 라인 다음에 추가:

```python
    interval = config.refresh_interval_minutes
    if not isinstance(interval, int) or interval <= 0:
        return 0
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 16 PASS (12 + 4 신규)

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "fix(v0.3.12): interval 가드 (isinstance int + > 0)"
```

---

## Task 7: marker 로드 실패 fallback + config 실패 silent

**Files:**
- Modify: `tests/scripts/test_on_recap.py` (코드 변경 없이 테스트만 추가 — 이미 구현 완료)

- [ ] **Step 1: 테스트 추가 (config 실패 + marker 실패 fallback)**

`tests/scripts/test_on_recap.py` 에 추가:

```python
def test_config_load_failure_silent(session_stdin, temp_root, capsys, monkeypatch):
    """config.toml 이 invalid TOML 이면 silent fail."""
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text("not valid toml = = =", encoding="utf-8")
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_marker_missing_falls_back_to_normal_message(
    session_stdin, temp_root, capsys, monkeypatch
):
    """marker 파일 없음 → Marker.load 가 empty marker 반환 (wake_count=0) → 정상 메시지."""
    _freeze_kst(monkeypatch, 10, 0)
    (temp_root / "config.toml").write_text(
        'mode = "auto"\nrefresh_interval_minutes = 50\nmax_refresh_count = 10\n',
        encoding="utf-8",
    )
    # marker 파일 안 만듦
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "살리러 갈게요" in out["systemMessage"]
```

- [ ] **Step 2: 테스트 실행 → PASS (이미 구현됨)**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 18 PASS (16 + 2 신규)

- [ ] **Step 3: commit (테스트만 추가)**

```bash
git add tests/scripts/test_on_recap.py
git commit -m "test(v0.3.12): config/marker silent fail + fallback 케이스"
```

---

## Task 8: 기존 PING 회귀 가드 (refresh.py 불변)

**Files:**
- Modify: `tests/scripts/test_on_recap.py` (regression guard 추가)

- [ ] **Step 1: 회귀 테스트 추가**

`tests/scripts/test_on_recap.py` 에 추가:

```python
def test_refresh_ping_format_unchanged():
    """recap 추가가 기존 PING 형식 변경 X (regression guard)."""
    from scripts.refresh import _build_ping, PING_PREFIX
    ping = _build_ping(wake_count=1, max_count=10)
    assert ping.startswith(PING_PREFIX)
    assert "reply with exactly" in ping
    assert "1/10" in ping
    assert "Use minimal output tokens" in ping
```

- [ ] **Step 2: 테스트 실행 → PASS (refresh.py 무변경)**

Run: `uv run pytest tests/scripts/test_on_recap.py::test_refresh_ping_format_unchanged -v`
Expected: PASS

- [ ] **Step 3: commit**

```bash
git add tests/scripts/test_on_recap.py
git commit -m "test(v0.3.12): refresh.py PING 형식 회귀 가드"
```

---

## Task 9: version bump + CHANGELOG

**Files:**
- Modify: `pyproject.toml`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: pyproject.toml version 확인 + bump**

Run: `grep '^version' pyproject.toml`
Expected: `version = "0.3.11"`

다음으로 교체:
```toml
version = "0.3.12"
```

- [ ] **Step 2: .claude-plugin/plugin.json version bump**

Run: `grep '"version"' .claude-plugin/plugin.json`
Expected: `"version": "0.3.11"`

다음으로 교체:
```json
"version": "0.3.12"
```

- [ ] **Step 3: commit**

```bash
git add pyproject.toml .claude-plugin/plugin.json
git commit -m "chore(v0.3.12): version bump 0.3.11 → 0.3.12"
```

---

## Task 10: 전체 pytest + 수동 검증 + PR

**Files:** 없음 (검증 + push 만)

- [ ] **Step 1: 전체 pytest 통과 확인**

Run: `uv run pytest -v`
Expected: 150 PASS (기존 131 + 신규 19)

- [ ] **Step 2: branch 푸시**

```bash
git push -u origin feature/v0.3.12-recap-message
```

- [ ] **Step 3: 사용자한테 수동 검증 요청 (PR 생성 전)**

사용자한테 다음 메시지 전달:

> recap 기능 v0.3.12 구현 완료. 머지 전 사용자 수동 검증 필요:
> 
> 1. test 세션에서 prompt 1회 입력 + Claude 응답
> 2. turn 종료 즉시 chat UI 의 systemMessage 영역에 "🪦 캐시는 HH:MM KST 에 살리러 갈게요!" 표시 확인
> 3. ~50분 후 기존 PING (`[cn:keepalive ...]` → `ok @HH:MM (N/M)`) 정상 동작 확인
> 4. log 파일 (`cn.log`) 에서 on_recap.py + refresh.py 둘 다 실행됐는지 확인
> 5. `/cn:status` 결과에서 wake_count, latest_fire 정상 갱신 확인
> 
> 검증 OK 면 PR 생성 + 머지 진행 (사용자 명시 승인 후).

- [ ] **Step 4: 사용자 검증 OK 후 PR 생성**

```bash
gh pr create --title "feat(v0.3.12): cache recap message — Stop fire 즉시 wake 시각 표시" --body "$(cat <<'EOF'
## Summary

- Stop hook fire 시점에 systemMessage 로 "다음 wake 시각" 즉시 표시 (recap 영역)
- sync hook (on_recap.py 신규) + async hook (refresh.py 기존) 분리 구조
- mode 별 메시지 분기 (auto/hybrid/notify + system_notification true/false)
- max_refresh_count 도달 시 사용자 액션 안내 메시지
- silent fail top-level wrap (PRD 불변 보장)
- 신규 테스트 19개 (총 150 PASS)

Spec: `docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md`

## Test plan

- [x] pytest 150/150 통과
- [ ] 사용자 수동 검증 — systemMessage UI 표시 + 기존 PING 정상 + log 확인
EOF
)"
```

- [ ] **Step 5: 사용자 머지 명시 승인 대기**

CLAUDE.md 룰 — "머지는 반드시 사용자 승인 후 실행". PR 생성 후 사용자한테 보고 + 머지 명령 대기.

---

## Self-Review 결과

**Spec coverage:**
- §2 포함 항목 4개 (sync hook, HH:MM 계산, max_count 분기, mode 분기) — Task 1~5 커버 ✅
- §3.1 hooks.json 구조 — Task 1 ✅
- §3.2 수동 검증 절차 — Task 10 ✅
- §3.3 mode 별 메시지 (5 케이스) — Task 4-5 ✅
- §3.4 silent fail top-level + 5 silent fail 케이스 — Task 2, 6, 7 ✅
- §5 의사코드 → §6 테스트 19개 — Task 1-8 ✅
- §7 v0.3.12 마일스톤 + §8 version bump — Task 9 ✅
- §9 결정 기록 — spec 에 이미 있음

**Placeholder scan:** 없음. 모든 step 에 실제 코드/명령.

**Type consistency:**
- `_build_message(death_hhmm, mode, system_notification, maxed_out)` 시그니처 — Task 4 에서 3-arg 로 도입 → Task 5 에서 4-arg 로 교체 (의도된 진화, plan 내 명시)
- `_main_impl()` 의 점진적 확장 — 각 task 마다 최종 형태 명시

**스코프:** single implementation plan 내 완결. 분해 불필요.

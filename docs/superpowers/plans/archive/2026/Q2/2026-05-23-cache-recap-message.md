# Cache Recap Message Implementation Plan (revised)

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Sub-skill: superpowers:executing-plans 또는 main 직접 진행.

**Goal:** Stop hook fire 즉시 사용자에게 "다음 wake 시각" systemMessage 표시 (local time, 4 언어).

**Architecture:**
- sync hook (`on_recap.py`) + async hook (`refresh.py` 기존) 분리
- 메시지 단일화 (mode/max_count 분기 X)
- i18n via `lib/i18n.py` (ko/en/ja/zh)
- config 의 `[general].language` 명시 설정
- refresh.py PING 도 local time (KST hardcode 제거)

**Tech Stack:** Python 3.11+, pytest, freezegun, uv

**Spec:** `docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md`

**완료 task (이전 plan 에서):**
- Task 1: hooks.json sync hook 등록 ✅ (commit `91b24c9`)
- Task 2: on_recap.py 골격 + silent fail wrap ✅ (commit `def02ab` + fix `e223f8f`)

---

## File Structure

### 신규
- `lib/i18n.py` — 언어별 메시지 + format helper
- `tests/lib/test_i18n.py` — i18n 테스트

### 수정
- `lib/config.py` — `language` 필드 추가 + default "en"
- `tests/lib/test_config.py` — language 테스트
- `scripts/on_recap.py` — i18n 호출, local time, mode/max 분기 없음 (이미 골격 작성됨, 본문 갱신)
- `tests/scripts/test_on_recap.py` — 메시지 검증 갱신 (KST 제거, 4 언어)
- `scripts/refresh.py` — KST 제거, PING local time
- `tests/scripts/test_refresh.py` — KST 검증 갱신

---

## Task 3 (revised): lib/i18n.py + 테스트

**Files:**
- Create: `lib/i18n.py`
- Create: `tests/lib/test_i18n.py`

- [ ] **Step 1: test_i18n.py 작성**

`tests/lib/test_i18n.py` (신규):

```python
"""Tests for lib/i18n.py."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    build_recap_message,
    normalize_language,
)


def test_default_language_is_en():
    assert DEFAULT_LANGUAGE == "en"


def test_supported_languages_are_four():
    assert set(SUPPORTED_LANGUAGES) == {"ko", "en", "ja", "zh"}


@pytest.mark.parametrize("lang,hh,mm,expected", [
    ("ko", 10, 50, "🪦 캐시는 10시 50분에 죽어요."),
    ("en", 10, 50, "🪦 Cache dies at 10:50."),
    ("ja", 10, 50, "🪦 キャッシュは10時50分に死にます。"),
    ("zh", 10, 50, "🪦 缓存将在10点50分死亡。"),
    ("en", 0, 5, "🪦 Cache dies at 00:05."),
    ("ko", 0, 5, "🪦 캐시는 0시 5분에 죽어요."),
    ("en", 23, 59, "🪦 Cache dies at 23:59."),
])
def test_build_recap_message(lang, hh, mm, expected):
    assert build_recap_message(lang, hh, mm) == expected


def test_normalize_language_valid():
    for lang in ("ko", "en", "ja", "zh"):
        assert normalize_language(lang) == lang


@pytest.mark.parametrize("invalid", ["xx", "kor", None, 123, ""])
def test_normalize_language_invalid_falls_back_to_en(invalid, capsys):
    result = normalize_language(invalid)
    assert result == "en"
    assert "fallback" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: 테스트 실행 → FAIL (ImportError)**

Run: `uv run pytest tests/lib/test_i18n.py -v`
Expected: ImportError

- [ ] **Step 3: lib/i18n.py 작성**

`lib/i18n.py` (신규):

```python
"""recap 메시지 다국어 (ko/en/ja/zh).

PING 등 다른 메시지는 별도 PR 에서 i18n 화.
"""
import sys
from typing import Literal

Language = Literal["ko", "en", "ja", "zh"]
DEFAULT_LANGUAGE: Language = "en"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("ko", "en", "ja", "zh")


def _format_time(lang: Language, hh: int, mm: int) -> str:
    if lang == "ko":
        return f"{hh}시 {mm}분"
    if lang == "en":
        return f"{hh:02d}:{mm:02d}"
    if lang == "ja":
        return f"{hh}時{mm}分"
    if lang == "zh":
        return f"{hh}点{mm}分"
    return f"{hh:02d}:{mm:02d}"


def build_recap_message(lang: Language, hh: int, mm: int) -> str:
    time_str = _format_time(lang, hh, mm)
    if lang == "ko":
        return f"🪦 캐시는 {time_str}에 죽어요."
    if lang == "en":
        return f"🪦 Cache dies at {time_str}."
    if lang == "ja":
        return f"🪦 キャッシュは{time_str}に死にます。"
    if lang == "zh":
        return f"🪦 缓存将在{time_str}死亡。"
    return f"🪦 Cache dies at {time_str}."


def normalize_language(value: object) -> Language:
    if isinstance(value, str) and value in SUPPORTED_LANGUAGES:
        return value  # type: ignore[return-value]
    print(
        f"[cn:warn] unknown language={value!r}, fallback to {DEFAULT_LANGUAGE!r}",
        file=sys.stderr,
    )
    return DEFAULT_LANGUAGE
```

- [ ] **Step 4: 테스트 → PASS**

Run: `uv run pytest tests/lib/test_i18n.py -v`
Expected: ~12 PASS (parametrize 풀면 더)

- [ ] **Step 5: commit**

```bash
git add lib/i18n.py tests/lib/test_i18n.py
git commit -m "feat(v0.3.12): lib/i18n.py — 4 언어 recap 메시지 + fallback"
```

---

## Task 4 (revised): lib/config.py 에 language 필드 추가

**Files:**
- Modify: `lib/config.py`
- Modify: `tests/lib/test_config.py`

- [ ] **Step 1: test_config.py 에 language 테스트 추가**

`tests/lib/test_config.py` 에 (기존 파일 보고 적절한 위치에 추가):

```python
def test_config_language_default_is_en(tmp_path):
    """config 에 language 미지정 시 default = 'en'."""
    from lib.config import load_config
    config_path = tmp_path / "config.toml"
    config_path.write_text("[general]\nmode = \"auto\"\n", encoding="utf-8")
    config = load_config(config_path)
    assert config.language == "en"


def test_config_language_loaded_from_toml(tmp_path):
    """[general].language 값이 Config 에 반영."""
    from lib.config import load_config
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[general]\nmode = "auto"\nlanguage = "ko"\n', encoding="utf-8"
    )
    config = load_config(config_path)
    assert config.language == "ko"


def test_config_language_unknown_value_loaded_as_is(tmp_path):
    """load 단계는 validate X (normalize_language 단계에서 fallback)."""
    from lib.config import load_config
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[general]\nmode = "auto"\nlanguage = "xx"\n', encoding="utf-8"
    )
    config = load_config(config_path)
    assert config.language == "xx"
```

- [ ] **Step 2: 테스트 실행 → FAIL (Config 에 language 필드 없음)**

Run: `uv run pytest tests/lib/test_config.py -v -k language`
Expected: 3 FAIL (AttributeError)

- [ ] **Step 3: lib/config.py 에 language 필드 추가**

`Config` dataclass 에 필드 추가:
```python
@dataclass(frozen=True)
class Config:
    mode: Literal["notify", "auto", "hybrid"] = "hybrid"
    refresh_interval_minutes: int = 50
    max_refresh_count: int = 10
    language: str = "en"   # <-- 신규
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
```

`load_config` 의 `general = data.get("general", {})` 블록 다음에 `language = general.get("language", "en")` 추가하고 Config 생성 시 `language=language` 전달.

- [ ] **Step 4: 테스트 → PASS**

Run: `uv run pytest tests/lib/test_config.py -v`
Expected: 기존 테스트 + 3 language 테스트 PASS

- [ ] **Step 5: commit**

```bash
git add lib/config.py tests/lib/test_config.py
git commit -m "feat(v0.3.12): config 에 [general].language 필드 추가 (default 'en')"
```

---

## Task 5 (revised): on_recap.py 본문 — local time + i18n + interval 가드

**Files:**
- Modify: `scripts/on_recap.py`
- Modify: `tests/scripts/test_on_recap.py`

- [ ] **Step 1: test_on_recap.py 갱신**

기존 Task 3 의 KST/freeze_time 케이스 갱신 + 신규 4 언어 + interval 가드 + invalid language fallback 케이스 추가.

기존 `test_auto_mode_normal_message`, `test_midnight_rollover` 삭제 후 다음으로 교체:

```python
import freezegun


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_message_ko(session_stdin, temp_root, capsys):
    """ko + interval=50 + fire=10:00 local → '🪦 캐시는 10시 50분에 죽어요.'"""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\nlanguage = "ko"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    rc = main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["systemMessage"] == "🪦 캐시는 10시 50분에 죽어요."


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_message_en(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 10:50."


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_message_ja(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\nlanguage = "ja"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 キャッシュは10時50分に死にます。"


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_message_zh(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\nlanguage = "zh"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 缓存将在10点50分死亡。"


@freezegun.freeze_time("2026-05-23 23:55:00")
def test_midnight_rollover_en(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 30\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "🪦 Cache dies at 00:25."


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_default_language_en(session_stdin, temp_root, capsys):
    """config 에 language 없으면 'en'."""
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "Cache dies at 10:50" in out["systemMessage"]


@freezegun.freeze_time("2026-05-23 10:00:00")
def test_recap_invalid_language_falls_back_to_en(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text(
        '[general]\nmode = "auto"\nrefresh_interval_minutes = 50\nlanguage = "xx"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    main()
    out = json.loads(capsys.readouterr().out)
    assert "Cache dies at 10:50" in out["systemMessage"]


@pytest.mark.parametrize("interval", [0, -1, -100])
def test_invalid_interval_silent_fail(session_stdin, temp_root, capsys, interval):
    (temp_root / "config.toml").write_text(
        f'[general]\nmode = "auto"\nrefresh_interval_minutes = {interval}\nlanguage = "en"\n',
        encoding="utf-8",
    )
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_config_load_failure_silent(session_stdin, temp_root, capsys):
    (temp_root / "config.toml").write_text("not valid = = =", encoding="utf-8")
    from scripts.on_recap import main
    rc = main()
    assert rc == 0
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: 테스트 → FAIL (기존 메시지 형식 + KST 사용)**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 새 테스트 FAIL

- [ ] **Step 3: on_recap.py 갱신**

`scripts/on_recap.py` 의 `_KST` 제거, `_build_message_auto_hybrid` 제거, `_main_impl` 본문 교체.

위 import 라인 `from lib.config import ensure_config_file, load_config` 다음 줄에 추가:
```python
from lib.i18n import build_recap_message, normalize_language  # noqa: E402
```

`_KST = timezone(timedelta(hours=9))` 라인 제거. `from datetime import datetime, timedelta, timezone` 에서 `timezone` 제거 (사용 안 함).

`_build_message_auto_hybrid` 함수 제거.

`_main_impl` 본문 교체:

```python
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
    if not isinstance(interval, int) or interval <= 0:
        return 0

    lang = normalize_language(config.language)
    death_at = datetime.now() + timedelta(minutes=interval)
    message = build_recap_message(lang, death_at.hour, death_at.minute)
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0
```

- [ ] **Step 4: 테스트 → PASS**

Run: `uv run pytest tests/scripts/test_on_recap.py -v`
Expected: 새 케이스 + 기존 silent fail + hook 구조 모두 PASS

- [ ] **Step 5: commit**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(v0.3.12): on_recap local time + i18n (4 언어) + interval 가드"
```

---

## Task 6 (revised): refresh.py KST 제거 + PING local time

**Files:**
- Modify: `scripts/refresh.py`
- Modify: `tests/scripts/test_refresh.py`

- [ ] **Step 1: test_refresh.py 갱신**

기존 KST 검증 테스트 (있다면) 삭제 + 신규 회귀 추가:

```python
def test_build_ping_has_no_kst_suffix():
    from scripts.refresh import _build_ping
    ping = _build_ping(wake_count=1, max_count=10)
    assert "KST" not in ping


def test_build_ping_format_local_time():
    """형식: [cn:keepalive HH:MM, N/M] reply with exactly 'ok @HH:MM (N/M)'. ..."""
    import re
    from scripts.refresh import _build_ping, PING_PREFIX
    ping = _build_ping(wake_count=2, max_count=10)
    assert ping.startswith(PING_PREFIX)
    # HH:MM 형식 (KST suffix 없음)
    assert re.search(r"\[cn:keepalive \d{2}:\d{2}, 2/10\]", ping)
    assert re.search(r"reply with exactly 'ok @\d{2}:\d{2} \(2/10\)'", ping)
    assert "Use minimal output tokens" in ping
```

기존 KST 검증 테스트가 있으면 (예: `assert "KST" in ping`) 삭제 또는 위로 교체.

- [ ] **Step 2: 테스트 → FAIL (현재 KST 포함)**

Run: `uv run pytest tests/scripts/test_refresh.py -v -k ping`
Expected: 새 케이스 FAIL

- [ ] **Step 3: refresh.py 수정**

`scripts/refresh.py` 의 `_KST = timezone(timedelta(hours=9))` 제거. `from datetime import datetime, timedelta, timezone` 에서 `timezone` 제거.

`_build_ping` 함수 본문 교체:
```python
def _build_ping(wake_count: int, max_count: int) -> str:
    hhmm = datetime.now().strftime("%H:%M")
    nm = f"{wake_count}/{max_count}"
    return (
        f"{PING_PREFIX} {hhmm}, {nm}] "
        f"reply with exactly 'ok @{hhmm} ({nm})'. "
        "No tools, no analysis. Use minimal output tokens."
    )
```

- [ ] **Step 4: 테스트 → PASS**

Run: `uv run pytest tests/scripts/test_refresh.py -v`
Expected: 모든 refresh 테스트 PASS

- [ ] **Step 5: commit**

```bash
git add scripts/refresh.py tests/scripts/test_refresh.py
git commit -m "refactor(v0.3.12): refresh.py PING local time (KST hardcode 제거)"
```

---

## Task 7 (revised): version bump 0.3.11 → 0.3.12

**Files:**
- Modify: `pyproject.toml`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: pyproject.toml 갱신**

```toml
version = "0.3.12"
```

- [ ] **Step 2: plugin.json 갱신**

```json
"version": "0.3.12"
```

- [ ] **Step 3: commit**

```bash
git add pyproject.toml .claude-plugin/plugin.json
git commit -m "chore(v0.3.12): version bump 0.3.11 → 0.3.12"
```

---

## Task 8 (revised): 전체 pytest + 수동 검증 + PR

- [ ] **Step 1: 전체 pytest 통과**

Run: `uv run pytest -v`
Expected: ~155 PASS

- [ ] **Step 2: 브랜치 푸시**

```bash
git push -u origin feature/v0.3.12-recap-message
```

- [ ] **Step 3: 사용자 수동 검증 요청**

1. test 세션에서 prompt 1회 → Claude 응답 → turn 종료 즉시 systemMessage 영역에 메시지 표시
2. 메시지 형식: `🪦 캐시는 10시 50분에 죽어요.` (config 의 language 따라)
3. local time (KST 사용자면 KST, UTC 사용자면 UTC)
4. ~50분 후 기존 PING `[cn:keepalive HH:MM, N/M]` → `ok @HH:MM (N/M)` 정상 동작 (KST suffix 없음)
5. log 파일 (`cn.log`) 에서 on_recap.py + refresh.py 둘 다 실행 확인
6. `/cn:status` 정상 동작

- [ ] **Step 4: 사용자 OK 후 gh pr create**

```bash
gh pr create --title "feat(v0.3.12): cache recap message (local time, 4 lang i18n)" --body "$(cat <<'EOF'
## Summary

- Stop hook fire 시점에 systemMessage 로 "다음 wake 시각" 표시 (recap)
- 4 언어 i18n (ko/en/ja/zh) — config `[general].language` 명시 설정
- local time 사용 (KST hardcode 제거)
- refresh.py PING 도 local time + KST suffix 제거
- 신규: lib/i18n.py + scripts/on_recap.py + 테스트

Spec: docs/superpowers/specs/active/2026-05-23-cache-recap-message-design.md

## Test plan

- [x] pytest ~155/155 통과
- [ ] 사용자 수동 검증 — systemMessage 표시 + 4 언어 + local time + PING 정상
EOF
)"
```

- [ ] **Step 5: 사용자 머지 명시 승인 대기**

---

## Self-Review

**Spec coverage:**
- §3.1 hooks.json — Task 1 (완료) ✅
- §3.3 메시지 단일화 4 언어 — Task 3, 5 ✅
- §3.4 language config — Task 4 ✅
- §3.5 silent fail — Task 5 (interval 가드, config 실패) ✅
- §3.6 refresh.py PING local time — Task 6 ✅
- §5 lib/i18n.py — Task 3 ✅
- §6 on_recap.py — Task 5 ✅
- §7 테스트 케이스 — Task 3, 4, 5, 6 ✅

**Placeholder scan:** 없음.

**Type consistency:** `Language = Literal["ko","en","ja","zh"]`, `normalize_language(value: object) -> Language`, `build_recap_message(lang: Language, hh: int, mm: int)` — 일관.

**Scope:** single PR. OK.

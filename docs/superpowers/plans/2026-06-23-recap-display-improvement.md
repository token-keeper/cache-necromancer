# Recap 표시 개선 (박스 모드 + 소생 해골) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop hook recap 을 (1) config 옵트인 박스로 크게 보이게 하고 (2) 자동 갱신 turn 에서 소생 횟수를 ☠️ 로 표시한다.

**Architecture:** 폭계산 박스 렌더러(신규 순수 모듈) + config `[display]` 축 + i18n 소생 문구 + on_recap 이 transcript 신호로 wake turn 을 감지해 compact/box × 일반/소생 4 조합을 조립. refresh.py·marker 스키마·token-tracker 는 건드리지 않는다.

**Tech Stack:** Python 3.11+ stdlib only (`unicodedata`, `tomllib`, `json`, `re`), pytest + freezegun.

## Global Constraints

- 외부 의존성 금지 — stdlib 만 (hook 런타임은 `python3` 단독). 신규 런타임 패키지 추가 불가.
- PRD 불변: 어떤 실패도 chat 동작 차단 X — on_recap 은 모든 경로에서 silent fail(stdout empty + exit 0).
- 메시지 언어 4종: `ko | en | ja | zh`. 기본 `en`.
- `recap_style` 기본값 `compact` (기존 동작 회귀 0). 잘못된 값 → stderr 경고 + `compact` fallback.
- 해골 상한: N≤5 → `☠️`×N, N>5 → `☠️×N` 텍스트.
- TDD: 각 task 는 실패 테스트 → 실패 확인 → 최소 구현 → 통과 → 커밋.
- 커밋 컨벤션 `type(scope): 한글 설명`.

---

### Task 1: 폭계산 박스 렌더러 (`lib/box_render.py`)

**Files:**
- Create: `lib/box_render.py`
- Test: `tests/lib/test_box_render.py`

**Interfaces:**
- Produces:
  - `display_width(s: str) -> int` — 터미널 표시폭(이모지/CJK=2, VS16/ZWJ/combining=0, 그 외 1).
  - `render_box(lines: list[str], pad: int = 2) -> str` — round 테두리 박스 문자열(개행 포함).

- [ ] **Step 1: 실패 테스트 작성**

`tests/lib/test_box_render.py`:

```python
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.box_render import display_width, render_box


def test_display_width_ascii():
    assert display_width("Cache dies at 17:44") == 19


def test_display_width_skull_with_variation_selector():
    # ☠️ = U+2620 + U+FE0F → 표시폭 2 (FE0F 는 0)
    assert display_width("☠️") == 2


def test_display_width_tombstone_and_cjk():
    assert display_width("🪦") == 2          # U+1FAA6
    assert display_width("캐시") == 4         # CJK 2글자 × 2


def test_render_box_all_lines_same_display_width():
    lines = ["🪦  Cache dies at 17:44", "🔥  3 wakes · until 20:14"]
    out = render_box(lines).split("\n")
    widths = {display_width(l) for l in out}
    assert len(widths) == 1, f"행마다 폭 불일치: {widths}"


def test_render_box_border_chars():
    out = render_box(["x"]).split("\n")
    assert out[0][0] == "╭" and out[0][-1] == "╮"
    assert out[1][0] == "│" and out[1][-1] == "│"
    assert out[-1][0] == "╰" and out[-1][-1] == "╯"
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/lib/test_box_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.box_render'`

- [ ] **Step 3: 최소 구현**

`lib/box_render.py`:

```python
"""터미널 표시폭 계산 + round 박스 렌더 (순수 함수, 부수효과 0).

recap 박스 모드용. 이모지(2칸)·CJK(2칸)·variation selector(0칸) 보정으로
우변 테두리를 정렬한다. stdlib 만 사용.
"""
import unicodedata


def display_width(s: str) -> int:
    """문자열의 터미널 표시폭(컬럼 수) 합."""
    total = 0
    for ch in s:
        o = ord(ch)
        if o in (0x200D,) or 0xFE00 <= o <= 0xFE0F:  # ZWJ / variation selector
            continue
        if unicodedata.combining(ch):
            continue
        if (
            0x1F300 <= o <= 0x1FAFF
            or 0x2600 <= o <= 0x27BF
            or 0x1F000 <= o <= 0x1F2FF
            or o in (0x2B50, 0x2B55)
        ):
            total += 2
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


def render_box(lines: list[str], pad: int = 2) -> str:
    """lines 를 round 테두리 박스로 감싼 문자열(개행 포함)."""
    inner = max(display_width(l) for l in lines) + pad * 2
    out = ["╭" + "─" * inner + "╮"]
    for l in lines:
        fill = inner - display_width(l) - pad
        out.append("│" + " " * pad + l + " " * fill + "│")
    out.append("╰" + "─" * inner + "╯")
    return "\n".join(out)
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/lib/test_box_render.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add lib/box_render.py tests/lib/test_box_render.py
git commit -m "feat(recap): 폭계산 박스 렌더러 추가 (이모지·CJK·VS16 보정)"
```

---

### Task 2: config `[display] recap_style` 축

**Files:**
- Modify: `lib/config.py` (`DisplayConfig` 추가, `Config` 확장, `load_config` 파싱, `_DEFAULT_TEMPLATE`)
- Test: `tests/lib/test_config.py` (추가)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `DisplayConfig(recap_style: str = "compact")` (frozen dataclass)
  - `Config.display: DisplayConfig`
  - `VALID_RECAP_STYLES: tuple[str, ...] = ("compact", "box")`

- [ ] **Step 1: 실패 테스트 작성** — `tests/lib/test_config.py` 끝에 추가:

```python
def test_display_default_is_compact(tmp_path):
    from lib.config import load_config
    cfg = load_config(tmp_path / "none.toml")  # 파일 없음 → 기본값
    assert cfg.display.recap_style == "compact"


def test_display_box_parsed(tmp_path):
    from lib.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('[display]\nrecap_style = "box"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.display.recap_style == "box"


def test_display_invalid_falls_back_to_compact(tmp_path, capsys):
    from lib.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('[display]\nrecap_style = "huge"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.display.recap_style == "compact"
    assert "recap_style" in capsys.readouterr().err
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/lib/test_config.py -k display -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'display'`

- [ ] **Step 3: 구현** — `lib/config.py`:

(a) `VALID_ARMS` 아래에 추가:

```python
VALID_RECAP_STYLES: tuple[str, ...] = ("compact", "box")
```

(b) `NotifyConfig` dataclass 아래에 추가:

```python
@dataclass(frozen=True)
class DisplayConfig:
    """recap 표시 설정."""

    recap_style: str = "compact"  # compact = 한 줄 / box = 박스
```

(c) `Config` 에 필드 추가 (`notify` 줄 아래):

```python
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
```

(d) `load_config` 의 `return Config(` 직전에 파싱 추가:

```python
    display_data = data.get("display", {})
    recap_style = display_data.get("recap_style", "compact")
    if recap_style not in VALID_RECAP_STYLES:
        print(
            f"[cn:warn] invalid display.recap_style: {recap_style!r} — "
            "fallback to 'compact'",
            file=sys.stderr,
        )
        recap_style = "compact"
    display = DisplayConfig(recap_style=recap_style)
```

(e) `return Config(...)` 에 `display=display,` 추가 (`notify=notify,` 다음 줄):

```python
        wake=wake,
        notify=notify,
        display=display,
    )
```

(f) `_DEFAULT_TEMPLATE` 의 `[wake]` 블록 뒤에 추가:

```python
[wake]
arm = "manual"                        # manual = /cn:set 시에만 소생 / always = 매 turn 자동
grace_seconds = 60                    # 알림 후 wake 까지 대기 (notify.enabled=true 일 때)

[display]
recap_style = "compact"               # compact = 한 줄 / box = 박스로 크게
"""
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/lib/test_config.py -v`
Expected: PASS (display 3건 포함, 기존 테스트도 전부 통과)

- [ ] **Step 5: 커밋**

```bash
git add lib/config.py tests/lib/test_config.py
git commit -m "feat(config): [display] recap_style 축 추가 (compact|box, 기본 compact)"
```

---

### Task 3: i18n 소생 해골 문구

**Files:**
- Modify: `lib/i18n.py` (`build_skull`, `build_revived_message`)
- Test: `tests/lib/test_i18n.py` (추가)

**Interfaces:**
- Consumes: `lib.i18n._format_time`, `Language`
- Produces:
  - `build_skull(n: int) -> str` — N≤5 → `"☠️"*N`, N>5 → `f"☠️×{N}"`
  - `build_revived_message(lang: Language, n: int, hh: int, mm: int) -> str`

- [ ] **Step 1: 실패 테스트 작성** — `tests/lib/test_i18n.py` 끝에 추가:

```python
import pytest
from lib.i18n import build_skull, build_revived_message


@pytest.mark.parametrize("n,expected", [
    (1, "☠️"),
    (3, "☠️☠️☠️"),
    (5, "☠️☠️☠️☠️☠️"),
    (6, "☠️×6"),
    (10, "☠️×10"),
])
def test_build_skull(n, expected):
    assert build_skull(n) == expected


@pytest.mark.parametrize("lang,expected", [
    ("ko", "☠️☠️☠️  3번째 소생 — 17시 44분에 또 죽어요"),
    ("en", "☠️☠️☠️  Revived 3× — dies again at 17:44"),
    ("ja", "☠️☠️☠️  3回目の蘇生 — 17時44分にまた死にます"),
    ("zh", "☠️☠️☠️  第3次复活 — 17点44分再次死亡"),
])
def test_build_revived_message(lang, expected):
    assert build_revived_message(lang, 3, 17, 44) == expected


def test_build_revived_message_capped_skull():
    msg = build_revived_message("en", 7, 0, 5)
    assert msg == "☠️×7  Revived 7× — dies again at 00:05"
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/lib/test_i18n.py -k "skull or revived" -v`
Expected: FAIL — `ImportError: cannot import name 'build_skull'`

- [ ] **Step 3: 구현** — `lib/i18n.py` 의 `build_set_recap_line` 함수 아래에 추가:

```python
def build_skull(n: int) -> str:
    """소생 횟수 → 해골 문자열. N≤5 는 해골 N개, 초과는 폭 보호로 '☠️×N'."""
    return "☠️" * n if n <= 5 else f"☠️×{n}"


def build_revived_message(lang: Language, n: int, hh: int, mm: int) -> str:
    """wake turn recap 1줄째 — 소생 횟수(해골) + 새 만료 시각. 죽음 라인을 대체."""
    skull = build_skull(n)
    time_str = _format_time(lang, hh, mm)
    if lang == "ko":
        return f"{skull}  {n}번째 소생 — {time_str}에 또 죽어요"
    if lang == "en":
        return f"{skull}  Revived {n}× — dies again at {time_str}"
    if lang == "ja":
        return f"{skull}  {n}回目の蘇生 — {time_str}にまた死にます"
    if lang == "zh":
        return f"{skull}  第{n}次复活 — {time_str}再次死亡"
    return f"{skull}  Revived {n}× — dies again at {time_str}"
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m pytest tests/lib/test_i18n.py -v`
Expected: PASS (skull 5건 + revived 5건 포함)

- [ ] **Step 5: 커밋**

```bash
git add lib/i18n.py tests/lib/test_i18n.py
git commit -m "feat(i18n): 소생 해골·소생 메시지 4개국어 추가"
```

---

### Task 4: on_recap 통합 (wake 감지 + compact/box 렌더)

**Files:**
- Modify: `scripts/on_recap.py`
- Test: `tests/scripts/test_on_recap.py` (추가)

**Interfaces:**
- Consumes: `lib.box_render.render_box`, `lib.i18n.build_revived_message`, `lib.config.Config.display`
- Produces: `detect_wake_turn(transcript_path: str) -> tuple[bool, int]` (모듈 함수, 테스트 가능)

- [ ] **Step 1: 실패 테스트 작성** — `tests/scripts/test_on_recap.py` 끝에 추가:

```python
def _write_transcript(tmp_path, entries):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")
    return str(p)


def test_detect_wake_turn_true_with_count(tmp_path):
    from scripts.on_recap import detect_wake_turn
    path = _write_transcript(tmp_path, [
        {"type": "user", "isMeta": False, "message": {"role": "user", "content": "real prompt"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "..."}},
        {"type": "user", "isMeta": True, "message": {"role": "user",
         "content": "Stop hook feedback:\n[refresh.py]: [cn:keepalive @17:44, 3/5] reply ..."}},
    ])
    assert detect_wake_turn(path) == (True, 3)


def test_detect_wake_turn_false_for_real_prompt(tmp_path):
    from scripts.on_recap import detect_wake_turn
    path = _write_transcript(tmp_path, [
        {"type": "user", "isMeta": False, "message": {"role": "user", "content": "hello"}},
    ])
    assert detect_wake_turn(path) == (False, 0)


def test_detect_wake_turn_missing_file_returns_false():
    from scripts.on_recap import detect_wake_turn
    assert detect_wake_turn("/nonexistent/x.jsonl") == (False, 0)
    assert detect_wake_turn("") == (False, 0)


def test_detect_wake_turn_count_fallback_when_no_nm(tmp_path):
    from scripts.on_recap import detect_wake_turn
    path = _write_transcript(tmp_path, [
        {"type": "user", "isMeta": True, "message": {"role": "user",
         "content": "Stop hook feedback:\n[cn:keepalive broken ping"}},
    ])
    assert detect_wake_turn(path) == (True, 1)


@freeze_time("2026-05-23 10:00:00")
def test_box_style_normal_turn_wraps_message(temp_root, monkeypatch):
    import io
    (temp_root / "config.toml").write_text(
        '[general]\nlanguage = "en"\ncache_ttl_minutes = 50\n[display]\nrecap_style = "box"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "box-sid"})))
    monkeypatch.setattr("scripts.on_recap.is_latest_install", lambda: True)
    from scripts.on_recap import main
    import sys as _sys
    out = io.StringIO(); monkeypatch.setattr(_sys, "stdout", out)
    main()
    msg = json.loads(out.getvalue())["systemMessage"]
    assert msg.startswith("╭") and "🪦 Cache dies at 10:50." in msg


@freeze_time("2026-05-23 10:00:00")
def test_compact_wake_turn_shows_skull(temp_root, monkeypatch):
    import io
    (temp_root / "config.toml").write_text(
        '[general]\nlanguage = "en"\ncache_ttl_minutes = 50\n', encoding="utf-8")
    tpath = _write_transcript(temp_root, [
        {"type": "user", "isMeta": True, "message": {"role": "user",
         "content": "Stop hook feedback:\n[cn:keepalive @10:50, 2/5] reply ..."}},
    ])
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": "wake-sid", "transcript_path": tpath})))
    monkeypatch.setattr("scripts.on_recap.is_latest_install", lambda: True)
    from scripts.on_recap import main
    import sys as _sys
    out = io.StringIO(); monkeypatch.setattr(_sys, "stdout", out)
    main()
    msg = json.loads(out.getvalue())["systemMessage"]
    assert msg == "☠️☠️ Revived 2× — dies again at 10:50"
```

> 참고: 기존 메시지 테스트들은 `transcript_path` 없는 stdin → `detect_wake_turn("")` → `(False,0)` → 현행 죽음 라인 그대로라 회귀 없음.

- [ ] **Step 2: 실패 확인**

Run: `python3 -m pytest tests/scripts/test_on_recap.py -k "wake or box or compact_wake" -v`
Expected: FAIL — `ImportError: cannot import name 'detect_wake_turn'`

- [ ] **Step 3: 구현** — `scripts/on_recap.py`:

(a) 상단 import 에 추가:

```python
import re
```

그리고 lib import 블록 수정:

```python
from lib.box_render import render_box  # noqa: E402
from lib.config import ensure_config_file, load_config  # noqa: E402
from lib.i18n import (  # noqa: E402
    build_recap_message,
    build_revived_message,
    build_set_recap_line,
    normalize_language,
)
```

(b) `_resolve_session_id` 를 payload 분리 버전으로 교체:

```python
def _read_hook_input() -> dict:
    """Stop hook stdin payload(JSON) 1회 read. 실패 시 빈 dict."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _resolve_session_id(payload: dict) -> str:
    sid = payload.get("session_id", "")
    if sid:
        return sid
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


_KEEPALIVE_NM = re.compile(r"\((\d+)/\d+\)")


def detect_wake_turn(transcript_path: str) -> tuple[bool, int]:
    """transcript tail 의 최신 user 엔트리가 cn keepalive 면 (True, N).

    N = ping 의 (N/M) 에서 파싱(없으면 1). 실패/미존재 시 (False, 0).
    """
    if not transcript_path:
        return (False, 0)
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 65536))
            data = f.read()
    except OSError:
        return (False, 0)
    last_user: dict | None = None
    for raw in data.splitlines():
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and e.get("type") == "user":
            last_user = e
    if last_user is None or not last_user.get("isMeta"):
        return (False, 0)
    msg = last_user.get("message") or {}
    content = msg.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if "[cn:keepalive" not in text:
        return (False, 0)
    m = _KEEPALIVE_NM.search(text)
    return (True, int(m.group(1)) if m else 1)
```

(c) `_main_impl` 의 stdin/조립부 수정 — 기존:

```python
    sid = _resolve_session_id()
    if not sid:
```

를:

```python
    payload = _read_hook_input()
    sid = _resolve_session_id(payload)
    if not sid:
```

로 바꾸고, 메시지 조립부(기존 `message = build_recap_message(...)` ~ `print(...)`)를 교체:

```python
    lang = normalize_language(config.language)
    now = datetime.now()
    death_at = now + timedelta(minutes=ttl)

    wake, revive_n = detect_wake_turn(payload.get("transcript_path", ""))
    if wake:
        line1 = build_revived_message(lang, revive_n, death_at.hour, death_at.minute)
    else:
        line1 = build_recap_message(lang, death_at.hour, death_at.minute)
    lines = [line1]

    marker = Marker.load(sid_hash)
    if marker.set_budget_remaining > 0:
        survive_at = now + timedelta(
            minutes=marker.set_budget_remaining * config.refresh_interval_minutes + ttl
        )
        lines.append(
            build_set_recap_line(
                lang, marker.set_budget_remaining, survive_at.hour, survive_at.minute
            )
        )

    if config.display.recap_style == "box":
        message = render_box(lines)
    else:
        message = "\n".join(lines)

    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0
```

- [ ] **Step 4: 통과 확인 (신규 + 기존 회귀)**

Run: `python3 -m pytest tests/scripts/test_on_recap.py -v`
Expected: PASS (신규 6건 + 기존 전부)

- [ ] **Step 5: 커밋**

```bash
git add scripts/on_recap.py tests/scripts/test_on_recap.py
git commit -m "feat(recap): wake turn 소생 해골 + box 모드 렌더 통합"
```

---

### Task 5: config 예시·버전·CHANGELOG

**Files:**
- Modify: `config.toml.example`, `pyproject.toml`, `.claude-plugin/plugin.json`, `CHANGELOG.md`

**Interfaces:** 없음 (문서/메타)

- [ ] **Step 1: `config.toml.example` 에 `[display]` 추가** — `[wake]` 블록 뒤:

```toml
[wake]
arm = "manual"                        # manual = /cn:set 시에만 소생 / always = 매 turn 자동
grace_seconds = 60                    # 알림 후 wake 까지 대기 (notify.enabled=true 일 때)

[display]
recap_style = "compact"               # compact = 한 줄 / box = 박스로 크게
```

- [ ] **Step 2: 버전 bump 0.5.2 → 0.6.0**

`pyproject.toml`: `version = "0.5.2"` → `version = "0.6.0"`
`.claude-plugin/plugin.json`: `"version": "0.5.2"` → `"version": "0.6.0"`

- [ ] **Step 3: `CHANGELOG.md` 최상단(`# Changelog` 아래)에 항목 추가**

```markdown
## 0.6.0

### Added
- recap 박스 모드 — `[display] recap_style = "box"` 로 만료 표시를 박스로 크게 (기본 `compact`).
- 자동 갱신 turn 에서 소생 횟수를 ☠️ 로 표시 (N≤5 해골, 초과 `☠️×N`). ko/en/ja/zh.
- `lib/box_render.py` — 이모지·CJK·variation selector 보정 폭계산 박스 렌더러.
```

- [ ] **Step 4: 전체 테스트 + 버전 일치 확인**

Run: `python3 -m pytest -q && grep -H version pyproject.toml .claude-plugin/plugin.json`
Expected: 전부 PASS, 두 파일 모두 `0.6.0`

- [ ] **Step 5: 커밋**

```bash
git add config.toml.example pyproject.toml .claude-plugin/plugin.json CHANGELOG.md
git commit -m "chore(release): v0.6.0 — config 예시·버전·CHANGELOG"
```

---

## Self-Review (작성자 점검 결과)

**1. Spec coverage:**
- §4.1 박스 모드 → Task 2(config) + Task 4(렌더 분기) ✓
- §4.2 폭계산 → Task 1 ✓
- §4.3 wake 감지 + 소생 → Task 3(i18n) + Task 4(detect_wake_turn) ✓
- §6 에러 핸들링 → on_recap try/except 유지 + detect 폴백 (Task 4) ✓
- §7 테스트 매트릭스 → Task 1·2·3·4 테스트 ✓
- §8 버전/예시 → Task 5 ✓

**2. Placeholder scan:** 모든 step 에 실제 코드/명령 포함. "TBD"/"적절히" 없음. ✓

**3. Type consistency:** `detect_wake_turn -> (bool,int)`, `build_skull(int)->str`,
`build_revived_message(lang,int,int,int)->str`, `render_box(list[str])->str`,
`DisplayConfig.recap_style:str` — task 간 시그니처 일치. ✓

## 비고

- 박스 정렬은 터미널 monospace + 이모지 2칸 가정(spec §9). 알파 허용.
- `transcript_path` 누락 시 일반 turn 폴백이라 안전.

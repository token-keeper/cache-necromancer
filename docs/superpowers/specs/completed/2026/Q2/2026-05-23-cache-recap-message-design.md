# Cache Recap Message — Design (v0.3.12)

> Stop hook fire 시점에 사용자에게 "캐시 만료 시각" 을 Claude Code recap 영역(systemMessage) 으로 즉시 표시.
> 사용자 시스템 local time + config 명시 언어 (한/영/일/중) 지원.

## 1. 목적

- 사용자가 prompt → Claude 응답 후 turn 종료 시점에 **캐시가 죽는 시각을 명시적으로 인지**할 수 있도록 한다.
- 기존 PING (refresh_interval_minutes 만료 직전 wake) 와 **별개의 정보성 메시지** — wake 트리거 아님.
- 다국어 지원: 한국어, 영어, 일본어, 중국어 (4개).
- 사용자 시스템 local time 사용 (KST hardcode 폐기).
- 시각 계산 = `fire + cache_ttl_minutes` (`refresh_interval_minutes` 와 분리 — 후자는 wake 주기, ttl 보다 안전 마진 만큼 짧음).

## 2. 범위

### 포함
- Stop hook fire 시점 즉시 systemMessage 출력 (sync hook 신규)
- 시각 = `fire_time + config.cache_ttl_minutes` (사용자 local time)
- `config.cache_ttl_minutes` 신설 (default 60 = Anthropic 1h ext cache)
- 언어별 메시지 + 시각 표기 (4개)
- config 의 `[general].language` 명시 설정
- 기존 refresh.py PING 도 local time 으로 변경 (KST hardcode 제거)

### 제외 (YAGNI)
- 메시지 ON/OFF config key (항상 ON)
- 메시지 형식 커스터마이즈
- mode/max_count 분기 메시지 (단일 메시지로 통일)
- 시스템 locale 자동 감지 (config 명시만)
- PING 메시지 다국어 (기존 영어 prompt 유지 — LLM reply 약속 형식 보존)
- config.py 의 다른 필드 타입/범위 검증 추가 (별도 PR)

## 3. 메커니즘

### 3.1 hooks.json 구조

Stop 배열에 hook 객체 **2개** 등록 (배열 순서 = 실행 순서):

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
]
```

### 3.2 검증 근거

[Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks.md) — Hook Lifecycle Events, Configuration Structure, Async Hooks. claude-code-guide subagent 검증:
- Stop 배열 객체 2개 → 순차 실행
- `asyncRewake: true` 는 background 진입, 다른 sync hook 막지 않음
- asyncRewake 모드 stdout 캡처 타이밍 불확정 → sync hook 분리

수동 검증 절차 (PR 머지 전 필수): Task 10 참조.

### 3.3 systemMessage 메시지 (4 언어)

**공통 형식**: `🪦 {prefix} {hh}{sep}{mm}{suffix} {tail}`

| lang | 메시지 |
|------|--------|
| ko | `🪦 캐시는 H시 M분에 죽어요.` |
| en | `🪦 Cache dies at HH:MM.` |
| ja | `🪦 キャッシュはH時M分に死にます。` |
| zh | `🪦 缓存将在H点M分死亡。` |

시각 형식 (mode/max_count 무관 단일):

| lang | 시각 (예: 10시 50분) |
|------|---------------------|
| ko | `10시 50분` (앞 0 없음) |
| en | `10:50` (24h, zero-pad) |
| ja | `10時50分` (앞 0 없음) |
| zh | `10点50分` (앞 0 없음) |

**JSON 출력**:
```python
print(json.dumps({"systemMessage": message}, ensure_ascii=False))
```

### 3.4 language config

위치: `[general].language` (기존 `[general]` 섹션에 추가)

```toml
[general]
mode = "auto"
refresh_interval_minutes = 50         # wake 주기 (cache TTL 보다 짧음)
cache_ttl_minutes = 60                # recap 메시지 시각 = fire + ttl
max_refresh_count = 10
language = "ko"
```

- 값: `"ko"`, `"en"`, `"ja"`, `"zh"` (ISO 639-1)
- default: `"en"`
- invalid 값 → stderr warn + `"en"` fallback

### 3.5 silent fail (PRD 불변)

`main()` 전체 try/except Exception wrap. 어떤 예외도 chat 동작 차단 X.

silent fail 케이스:
- stdin session_id 없음 → stdout empty + exit 0
- sanitize ValueError (invalid session_id) → stdout empty + exit 0
- `cache_ttl_minutes` 가 int 아니거나 ≤ 0 → stdout empty + exit 0
- 예상 밖 예외 (datetime/json/print) → top-level 캐치 + stdout empty + exit 0

graceful degrade (silent fail 아님):
- config 로드 실패 (invalid TOML / OSError) → lib.config 가 default Config fallback. on_recap 은 default 값 (ttl=60, language="en") 으로 메시지 출력. lib.config 가 stderr 경고 출력.

### 3.6 refresh.py PING 변경 (local time)

기존:
```python
_KST = timezone(timedelta(hours=9))
hhmm = datetime.now(_KST).strftime("%H:%M")
return f"{PING_PREFIX} {hhmm} KST, {nm}] reply with exactly 'ok @{hhmm} ({nm})'. ..."
```

신규:
```python
hhmm = datetime.now().strftime("%H:%M")
return f"{PING_PREFIX} {hhmm}, {nm}] reply with exactly 'ok @{hhmm} ({nm})'. ..."
```

- `_KST` 제거
- `KST` suffix 제거
- HH:MM 형식 유지 (LLM reply 약속 — 변경 시 reply mismatch)
- `_KST` import 도 정리

## 4. 파일 변경

### 4.1 신규
- `lib/i18n.py` — 언어별 메시지 dict + format helper
- `scripts/on_recap.py` — sync hook 본체 (이미 Task 2 골격 작성 완료)
- `tests/lib/test_i18n.py` — i18n 테스트
- `tests/scripts/test_on_recap.py` — on_recap 테스트 (Task 1-2 작성 완료, 추가 갱신)

### 4.2 기존 수정
- `hooks/hooks.json` — Task 1 완료 (sync hook 추가)
- `lib/config.py` — `language` 필드 추가 + 검증 + default "en"
- `scripts/refresh.py` — KST 제거, PING local time
- `tests/lib/test_config.py` — language 케이스 추가
- `tests/scripts/test_refresh.py` — KST 제거 검증 갱신

### 4.3 변경 없음
- `scripts/on_user_prompt.py`, `scripts/on_session_end.py`
- `scripts/on_status_command.py`, `scripts/cn_status.py`
- `lib/marker.py`, `lib/notify.py`, `lib/logger.py`, `lib/session_id.py`

## 5. lib/i18n.py 의사코드

```python
"""recap 메시지 다국어 (ko/en/ja/zh).

PING / status 등 다른 메시지는 별도 PR 에서 i18n 화."""
from typing import Literal

Language = Literal["ko", "en", "ja", "zh"]
DEFAULT_LANGUAGE: Language = "en"
SUPPORTED_LANGUAGES: tuple[Language, ...] = ("ko", "en", "ja", "zh")


def _format_time(lang: Language, hh: int, mm: int) -> str:
    """언어별 시각 표기."""
    if lang == "ko":
        return f"{hh}시 {mm}분"
    if lang == "en":
        return f"{hh:02d}:{mm:02d}"
    if lang == "ja":
        return f"{hh}時{mm}分"
    if lang == "zh":
        return f"{hh}点{mm}分"
    # 안전망 (validate 통과 시 도달 X)
    return f"{hh:02d}:{mm:02d}"


def build_recap_message(lang: Language, hh: int, mm: int) -> str:
    """recap systemMessage 본문."""
    time_str = _format_time(lang, hh, mm)
    if lang == "ko":
        return f"🪦 캐시는 {time_str}에 죽어요."
    if lang == "en":
        return f"🪦 Cache dies at {time_str}."
    if lang == "ja":
        return f"🪦 キャッシュは{time_str}に死にます。"
    if lang == "zh":
        return f"🪦 缓存将在{time_str}死亡。"
    # 안전망
    return f"🪦 Cache dies at {time_str}."


def normalize_language(value: object) -> Language:
    """unknown 또는 invalid → DEFAULT_LANGUAGE + stderr warn."""
    if isinstance(value, str) and value in SUPPORTED_LANGUAGES:
        return value  # type: ignore[return-value]
    import sys
    print(
        f"[cn:warn] unknown language={value!r}, fallback to {DEFAULT_LANGUAGE!r}",
        file=sys.stderr,
    )
    return DEFAULT_LANGUAGE
```

## 6. on_recap.py 의사코드

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

    ttl = config.cache_ttl_minutes
    if not isinstance(ttl, int) or ttl <= 0:
        return 0

    lang = normalize_language(config.language)
    death_at = datetime.now() + timedelta(minutes=ttl)
    message = build_recap_message(lang, death_at.hour, death_at.minute)
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0
```

## 7. test 케이스

### 7.1 lib/i18n.py (tests/lib/test_i18n.py 신규)

1. `build_recap_message("ko", 10, 50)` → `"🪦 캐시는 10시 50분에 죽어요."`
2. `build_recap_message("en", 10, 50)` → `"🪦 Cache dies at 10:50."`
3. `build_recap_message("ja", 10, 50)` → `"🪦 キャッシュは10時50分に死にます。"`
4. `build_recap_message("zh", 10, 50)` → `"🪦 缓存将在10点50分死亡。"`
5. `build_recap_message("en", 0, 5)` → `"🪦 Cache dies at 00:05."` (zero-pad)
6. `build_recap_message("ko", 0, 5)` → `"🪦 캐시는 0시 5분에 죽어요."` (앞 0 없음)
7. `normalize_language("ko")` → `"ko"`
8. `normalize_language("unknown")` → `"en"` + stderr warn
9. `normalize_language(None)` → `"en"` + stderr warn
10. `normalize_language(123)` → `"en"` + stderr warn

### 7.2 scripts/on_recap.py (tests/scripts/test_on_recap.py 갱신)

11. 정상 ko + auto + interval=50 + fire=10:00 local → ko 메시지
12. 정상 en + interval=50 + fire=10:00 → en 메시지
13. ja, zh 각각 1 케이스
14. 자정 넘김 (fire=23:55, interval=30) → 00:25 (en) / 0시 25분 (ko)
15. language 없음 (config 기본) → en
16. language invalid ("xx") → en fallback
17. interval=0 → silent fail
18. interval=음수 → silent fail
19. interval=문자열 → silent fail (또는 load_config 단계 ValueError)
20. config 로드 실패 (invalid TOML) → silent fail
21. session_id 없음 → silent fail
22. top-level exception → silent fail
23. systemMessage JSON parsing 성공 + ensure_ascii=False (emoji raw)

### 7.3 hooks.json 구조 (Task 1 완료 — 유지)

24-26. 기존 3 테스트 그대로

### 7.4 lib/config.py (tests/lib/test_config.py 갱신)

27. config.language default = "en"
28. config.language = "ko" 정상 로드
29. config.language = "xx" — load_config 단계는 통과 (validate 는 normalize_language 단)

### 7.5 scripts/refresh.py (tests/scripts/test_refresh.py 갱신)

30. `_build_ping` 결과에 `KST` substring 없음
31. `_build_ping` 결과 형식: `[cn:keepalive HH:MM, N/M] reply with exactly 'ok @HH:MM (N/M)'. ...`
32. (회귀) PING_PREFIX, "Use minimal output tokens", N/M format 유지

총 신규 + 갱신: ~32 케이스. 기존 baseline 131 → ~155 (일부 기존 케이스 갱신).

## 8. 마일스톤 위치

- v0.3.12 (현재 PR feature/v0.3.12-recap-message)
- 단일 PR — recap + i18n + PING local time

## 9. 영향도

- pytest baseline: 131 → ~155
- refresh.py PING 형식 변경 — Claude Code 가 PING reply ("ok @HH:MM (N/M)") 형식 그대로 유지 (KST suffix 만 제거). LLM 호환성 영향 X
- 기존 KST 메시지 표시되던 사용자 환경 — local time 이 KST 와 같으면 변화 X. 다른 timezone 사용자에게는 의도된 동작 변경
- 신규 의존성 없음 (freezegun 은 이미 dev dependency)

## 10. 결정 기록

- **systemMessage 채널**: Stop hook 공식 JSON 결과 필드. UI 시스템 메시지 영역 표시 보장
- **sync + async hook 분리**: asyncRewake true 모드 stdout 캡처 타이밍 불확정. sync hook 분리로 turn 종료 즉시 stdout 보장
- **메시지 단일화 (mode/max 분기 제거)**: 사용자 결정. "정보성 안내" 단일 메시지로 충분. 정확성보다 단순성 우선
- **local time 채택**: 사용자 요청. KST 사용자 외 사용자한테 의미 명확. 시스템 timezone 따름
- **언어 config 명시 설정**: locale 자동 감지보다 명시. 잘못된 locale env 회피
- **default 언어 = "en"**: international fallback
- **PING 메시지 i18n 제외**: LLM reply 약속 형식 (`ok @HH:MM (N/M)`) 유지 필수. KST suffix 만 제거
- **emoji `🪦` 사용**: 사용자 명시 승인. `ensure_ascii=False` 명시
- **YAGNI**: 메시지 ON/OFF, 형식 커스터마이즈, 추가 언어 — 후속 PR

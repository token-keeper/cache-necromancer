# `/cn:config` → 터미널 TUI 전환 설계 (v0.7.0)

> 작성일: 2026-06-24 · 상태: active · 기획 방식: grill-me 8문답으로 구체화

---

## 1. 한 줄 요약

cache-necromancer 의 **설정 변경**을 "Claude 와의 LLM 대화" 에서 **터미널 TUI** 로 옮긴다.
목표는 **LLM turn 0 + context window 0** — 설정 작업이 대화 맥락을 전혀 차지하지 않게 한다.

---

## 2. 배경 — 왜 바꾸나 (통증)

### 현재 `/cn:config` 의 정체

`commands/cn:config.md` 는 **인터랙티브 LLM 명령**이다:

```yaml
allowed-tools: AskUserQuestion, Read, Edit, Write
```

흐름:

1. Claude(LLM)가 `config.toml` 을 `Read`
2. `AskUserQuestion` 으로 **4개 질문을 한 번에** 물어봄 (사용자가 옵션 선택)
3. 답을 받아 `Edit` 으로 config 갱신

이 과정 전체가 **모델(LLM)을 거친다**. 그래서:

- **느리다** — 설정 하나 바꾸는데 모델 추론이 여러 번 돈다
- **context 를 먹는다** — 질문·답변·도구 호출이 transcript 에 쌓여, 이후 모든 turn 의 입력 토큰에 누적된다

### 핵심 개념: `turn 0` ≠ `context 0`

이번 기획에서 가장 중요한 깨달음. 둘은 **다른 개념**이다.

| 개념 | 뜻 |
|---|---|
| **LLM turn** | 모델이 추론을 한 번 도는 것 |
| **context window 점유** | 그 입력·출력이 대화 기록(transcript)에 남아, **다음 turn 들의 입력 토큰**에 포함되는 것 |

→ **turn 이 0 이어도 context 는 먹을 수 있다.** (기록만 남으면 토큰 소비)

### 명령별 현황

| 명령 | LLM turn | context 점유 | 비고 |
|---|---|---|---|
| `/cn:set` | **0** | 약간 | UserPromptExpansion hook 으로 처리 (모델 안 거침). 단 hook 출력이 transcript 에 남아 context 소량 소비 — `suppressOutput: true` 로 제거 가능 (별도 과제) |
| **`/cn:config`** | **多** | **多** | **AskUserQuestion 대화 → 본 설계가 겨냥하는 진짜 통증** |

즉 `/cn:set` 은 이미 빠르다(turn 0). 진짜 무거운 건 `/cn:config` 의 **인터랙티브 대화**다.

---

## 3. 해법 개요

설정을 **터미널 TUI** (`cn_config.py`) 가 담당한다.

- Claude(LLM)를 **전혀 거치지 않는다** → turn 0 + context 0
- `config.toml` 을 **직접 읽고 쓴다**
- 번호 선택 메뉴로 **"고르는" UX 는 그대로 유지** (통증의 근원은 "인터랙티브" 가 아니라 "LLM 대화" 였음)

```
[기존] 설정 = LLM 대화 (느림 + context 먹음)
[변경] 설정 = 터미널 TUI (turn 0 + context 0, 고르는 UX 유지)
```

---

## 4. 동작 흐름 (Before / After)

### Before

```
사용자: /cn:config
  → Claude(LLM) 가 config.toml Read
  → AskUserQuestion (질문 4개) ──┐
  ← 사용자 선택                  │  ← 모델 추론 + 대화 왕복
  → Claude 가 Edit 로 저장        │     (turn 多, context 누적)
  ← "변경 완료" ─────────────────┘
```

### After

```
사용자: /cn:config
  → UserPromptExpansion hook (turn 0) 이 가로채
  ← "새 터미널에서 아래를 실행하세요:
       python3 <경로>/cn_config.py"           ← 런처 안내만, 모델 안 거침

사용자: (새 터미널) python3 .../cn_config.py
  → TUI 가 config.toml 읽어 현재값 표시
  → 번호 메뉴로 항목별 선택
  → config.toml 직접 저장
  → "다음 Stop hook 부터 적용"                 ← Claude 와 무관, context 0
```

> **참고**: Claude 의 `!` shell escape 는 보통 비대화형(출력만 캡처, stdin 없음)이라 TUI 의 `input()` 이 깨질 수 있다. 그래서 1차 타겟은 **새 터미널 실행**이다. `!` 대화형 가능 여부는 추후 검증하여, 되면 한방 호출을 보너스로 추가한다 (현 설계를 깨지 않는 확장).

---

## 5. 설계 결정 (grill-me 8문답 요약)

| # | 질문 | 결정 | 이유 |
|---|---|---|---|
| Q1 | 핵심 통증? | **속도** (1차), context (근접 2차) | 출발점이 "설정이 느리다" |
| Q2 | turn 0 ≠ context 0 인가? | **맞다** | block 처리 출력도 transcript 에 남아 context 소비 |
| Q3 | 어떤 형태로 우회? | **터미널 TUI** | 인터랙티브 UX 유지하며 LLM 대화만 제거. 웹서버(무거움)·단발명령(불친절) 사이 스윗스팟 |
| Q4 | 범위? | **cn 전용** | 통증이 cn 에서 출발. 범용은 추상화 비용 큼 (YAGNI). 단 이식 문서화 |
| Q5 | TUI 라이브러리? | **순수 stdlib 번호메뉴** | cn 의 "의존성 0" 정체성 유지 → 이식 최적. 별로면 추후 curses/questionary |
| Q6 | 호출 + 기존 명령? | **`/cn:config` hook 이 런처 안내(turn 0), 기존 LLM 버전 폐기** | 발견성 유지 + LLM 대화 제거 |
| Q7 | 설정 항목 범위? | **사용자 설정 키 전부** | TUI 는 context 안 먹으니 항목 늘려도 비용 0 (LLM 대화와 정반대) |
| Q8 | 이식 구조? | **단일 파일 + SCHEMA 분리** | self-contained·복붙 이식 최적. 물리 분리는 과함 |

---

## 6. 아키텍처 (파일별)

| 파일 | 작업 | 역할 |
|---|---|---|
| `scripts/cn_config.py` | **신규** | stdlib 번호메뉴 TUI. `SCHEMA` 선언 + 범용 렌더/선택 엔진 + config 읽기·쓰기 |
| `scripts/on_status_command.py` | **수정** | `/cn:config` 라우팅 추가 → turn 0 으로 TUI 실행 안내 출력 |
| `commands/cn:config.md` | **전환** | 기존 인터랙티브 LLM(AskUserQuestion) 정의 폐기 |
| `tests/scripts/test_cn_config.py` | **신규** | SCHEMA 파싱·라인보존 쓰기·값 정규화 검증 |
| `lib/config.py` | **재사용** | tomllib 로드 + 라인보존 쓰기 (다른 키·주석 안 깨먹게) |

---

## 7. TUI UX (화면 예시)

순수 stdlib 번호 메뉴. 현재값은 `✓` 로 표시.

```
╭─ cache-necromancer 설정 ─────────────────╮

[1/7] wake.arm — 소생 방식
   1) manual   ✓  (현재)   /cn:set 충전분만 소생, 알림은 계속
   2) always       매 turn 자동 arm — 깜빡 보호, wake 비용 발생
   선택 (Enter=유지): _

[2/7] notify.enabled — macOS 알림
   1) true    ✓  (현재)
   2) false
   선택 (Enter=유지): _

...

[7/7] cache_ttl_minutes — 캐시 수명(분)
   1) 60      ✓  (현재)
   2) 직접 입력
   선택 (Enter=유지): _

╰──────────────────────────────────────────╯
변경: wake.arm  manual → always
저장됨 → 다음 Stop hook 부터 적용.
```

- 항목당 번호 입력 또는 Enter(현재값 유지)
- 자유 입력 필요한 키(`cache_ttl`, `language` 등)는 "직접 입력" 옵션
- 끝에 변경 요약 + 저장

---

## 8. SCHEMA 구조 (이식의 핵심)

설정 항목을 **데이터로 선언**한다. 엔진은 이 데이터만 보고 메뉴를 그린다.

```python
# 각 항목 = {키 경로, 라벨, 타입, 옵션}
SCHEMA = [
    {
        "key": ["wake", "arm"],          # config.toml 의 [wake].arm
        "label": "소생 방식",
        "type": "choice",
        "options": [
            ("manual", "/cn:set 충전분만 소생, 알림은 계속"),
            ("always", "매 turn 자동 arm — 깜빡 보호, wake 비용"),
        ],
    },
    {
        "key": ["notify", "enabled"],
        "label": "macOS 알림",
        "type": "bool",
    },
    {
        "key": ["general", "cache_ttl_minutes"],
        "label": "캐시 수명(분)",
        "type": "int",
        "options": [("60", "기본")],     # + 직접 입력
    },
    # ... recap_style, language, refresh_interval_minutes, max_refresh_count
]
```

**노출 항목**: `wake.arm` · `notify.enabled` · `refresh_interval_minutes` · `max_refresh_count` · `display.recap_style`(박스/compact) · `language` · `cache_ttl_minutes`.
**제외**: `wake.grace_seconds` (advanced — 직접 편집 안내).

---

## 9. config 읽기 / 쓰기 (라인 보존)

- **읽기**: `lib/config.py` 의 `tomllib` 로드 재사용
- **쓰기**: tomllib 은 읽기 전용 → 기존 `/cn:config` 와 동일하게 **해당 키 라인만 교체**
  - 사용자가 손댄 다른 키(`grace_seconds` 등)·주석을 **보존**
  - 파일 없으면 v0.5.0 기본 템플릿으로 생성
- **적용 시점**: config 는 매 hook fire 시 다시 읽힘 → **다음 Stop hook 부터 자동 적용**, 재시작 불필요

---

## 10. 이식 가이드 ⭐ (다른 플러그인으로)

이 TUI 를 다른 플러그인에 가져가는 법. **2가지만 바꾸면 끝.**

1. **`cn_config.py` 파일 복사**
2. **`SCHEMA` 배열 교체** — 그 플러그인의 설정 항목으로 (키 경로·라벨·옵션)
3. **config 파일 경로 1줄 수정** — `_resolve_root()` 의 `~/.cache-necromancer` → 대상 플러그인 경로

엔진(렌더·선택 루프·라인보존 쓰기)은 **그대로**. 의존성 0(stdlib only)이라 복붙 즉시 동작.

```
[범용 — 그대로]   렌더 엔진 · 선택 루프 · 라인보존 쓰기 · 값 정규화
[특화 — 교체]     SCHEMA 배열 · config 파일 경로
```

> 이 경계 덕분에 단일 파일을 유지하면서도 이식 비용이 거의 0 이다.

---

## 11. 비범위 (이번 PR 에서 제외)

| 항목 | 사유 |
|---|---|
| `/cn:set` 의 `suppressOutput: true` | grill 중 발견한 별개 통증(set hook context 소량). 관심사 다름 → **별도 PR** |
| 범용 멀티플러그인 허브 | YAGNI. cn 전용으로 패턴 검증 후 판단 |
| `!` 한방 대화형 호출 | TTY 가능 여부 검증 후 비파괴적 확장 |
| 화살표 네비(curses/questionary) | 번호메뉴 먼저 써보고 별로면 |

---

## 12. 테스트 계획

- `SCHEMA` → 메뉴 렌더 정확성
- 번호 입력 → 값 매핑 / Enter → 현재값 유지
- config 쓰기: 변경 키만 갱신, 다른 키·주석 보존
- 파일 없을 때 템플릿 생성
- 값 정규화 (bool/int/choice, 자유 입력)

---

## 13. 버전

**0.7.0** (minor) — 설정 UX 의 구조적 변경(`/cn:config` 동작 방식 전환)이므로 patch 가 아닌 minor.

---

## 14. 미해결 / 검증 필요

1. **`!` shell escape 가 대화형 stdin 을 주는가** — 안 주면 새 터미널 전용 확정 (현 설계 그대로 동작)
2. **번호메뉴 UX 체감** — 별로면 Q5 의 2/3(curses/questionary) 재검토
3. **TUI 실행 발견성** — `/cn:config` 런처 안내 + 문서로 충분한지

# Recap 표시 개선 — 박스 모드 + 소생 해골 (v0.6.0)

- 상태: active
- 작성일: 2026-06-23
- 도메인: cache-necromancer
- 관련 할일: `stop-캐시-만료-표시-크게-보기-모드-378aec55` (만료 표시 개선 — 크게 + ☠️ 재미)

## 1. 배경 / 문제

Stop hook(`scripts/on_recap.py`)이 turn 종료 시 `{"systemMessage": "🪦 Cache dies at HH:MM."}`
를 내보내고, Claude Code 가 `⎿ Stop says: 🪦 Cache dies at 17:44.` 한 줄로 작게 렌더한다.

두 가지 불편:

1. **가독성** — 한 줄이라 너무 작아 만료 시각이 눈에 안 들어온다.
2. **밋밋함** — 자동 갱신(wake)으로 캐시가 소생해도 표시가 똑같아 재미·피드백이 없다.

## 2. 목표

1. **박스 모드** — recap 을 폭 계산된 박스로 감싸 시각적 존재감을 키운다. config 옵트인.
2. **소생 해골** — 자동 갱신 turn 에서만 소생 횟수를 ☠️ 로 표시한다.

비목표(YAGNI): FIGlet/ASCII 아트 글자(검토 후 기각 — 가독성·폭·다국어 비용), 알파벳 큰
글자, compact 모드 폐기, 색상(ANSI) 도입.

## 3. 현재 구조 (참조)

- `scripts/on_recap.py` — Stop hook(sync). config·marker 읽어 `build_recap_message`(+ set 예산
  2줄째) 조립 후 `{"systemMessage": ...}` 출력. 실패는 silent.
- `lib/i18n.py` — `build_recap_message(lang,hh,mm)`, `build_set_recap_line(...)` (ko/en/ja/zh).
- `lib/config.py` — `Config` dataclass, `[general]/[notify]/[wake]` 파싱.
- `lib/marker.py` — per-session marker(JSON). `wake_count`, `set_budget_remaining` 등.
- `scripts/refresh.py` — asyncRewake. wake 시 stderr 로 `[cn:keepalive HH:MM, N/M] reply ...` ping.

## 4. 설계

두 기능은 **독립**이다. `recap_style` 은 framing(박스/플레인), 소생 해골은 turn 종류(wake/일반)에
달려 있어 서로 직교한다. 4 조합 모두 성립:

| | 일반 turn | wake turn |
|---|---|---|
| compact | `🪦 Cache dies at 17:44.` (현행) | `☠️☠️☠️ Revived 3× — dies again at 17:44` |
| box | 죽음 라인 박스 | 소생 라인 박스 |

### 4.1 박스 모드 (`recap_style`)

- config `[display] recap_style` ∈ {`compact`, `box`}, **기본 `compact`**.
  - 잘못된 값 → stderr 경고 후 `compact` fallback (기존 config 검증 패턴과 동일).
- `compact` = 현행 동작 그대로 (회귀 0).
- `box` = 조립된 recap 라인(들)을 `render_box()` 로 감싼다. **기존 i18n 문구를 그대로 재사용** —
  박스는 테두리/패딩만 추가하며 번역 문자열은 건드리지 않는다.

### 4.2 폭 계산 (`lib/box_render.py`, 신규)

박스 우변 정렬의 핵심은 **표시폭(terminal column width)** 기준 패딩이다. `len()` 은 이모지·CJK 에서
틀어진다.

```python
def display_width(s: str) -> int:
    # 문자별 폭 합. 이모지/CJK = 2, variation selector(FE0F)/ZWJ/combining = 0, 그 외 1.
```

규칙:

- `U+FE00–U+FE0F`(variation selector, ☠️=`U+2620 U+FE0F`), `U+200D`(ZWJ), `unicodedata.combining()` ⇒ 0
- 이모지/기호 범위(`U+1F300–U+1FAFF`, `U+2600–U+27BF`, `U+1F000–U+1F2FF`, `U+2B50/2B55`) ⇒ 2
- `east_asian_width` ∈ {`W`,`F`}(CJK 등) ⇒ 2
- 그 외 ⇒ 1

```python
def render_box(lines: list[str], pad: int = 2) -> str:
    inner = max(display_width(l) for l in lines) + pad*2
    # ╭─╮ / │ pad + line + (inner - width(line) - pad) 공백 / ╰─╯
```

테두리 문자: `╭ ─ ╮ │ ╰ ╯` (round). 한 박스 안에 1~2줄(죽음/소생 + 선택적 set 예산).

> 참고: v0.3.x 에서 삭제된 `lib/box_renderer.py` 와는 별개의 작고 집중된 신규 모듈이다 (부활 아님).

### 4.3 소생 해골 (wake turn 감지)

**감지 = transcript 신호** (marker race 회피, 결정적):

- on_recap 은 Stop hook stdin payload 의 `transcript_path` 를 읽는다 (현재는 미사용, payload 에는 존재).
- transcript tail 에서 **가장 최근 `type=="user"` 엔트리**를 찾아:
  - `isMeta == true` 이고 `message.content`(문자열화) 에 `"[cn:keepalive"` 포함 ⇒ **wake turn**.
- 이 신호는 token-tracker 측 동일 버그(`docs/explainers/autowake-token-stale`) 와 같은 마커를 쓴다.
- tail 만 읽는다(파일 끝에서 마지막 user 라인 1개). 실패/미존재 ⇒ 일반 turn 으로 폴백(silent).

**marker 기반 감지를 쓰지 않는 이유**: `_do_notify` 도 `wake_count`/`last_wake_at` 를 증가시켜서
(refresh.py) notify-only 이벤트와 실제 wake 를 구분할 수 없다. transcript 신호는 실제 wake(=ping 도달)
turn 에서만 참이라 오염이 없다.

**소생 횟수 N**: 동일 user 엔트리 content 의 ping 에서 `(N/M)` 의 N 을 정규식 파싱
(`r"\((\d+)/\d+\)"`). 파싱 실패 시 `1` 로 폴백.

**해골 문자열** (`lib/i18n.py build_skull`):

```python
def build_skull(n: int) -> str:
    return "☠️" * n if n <= 5 else f"☠️×{n}"
```

**소생 메시지** (`build_revived_message(lang, n, hh, mm)`, 4개국어). 죽음 라인을 대체한다(소생했으니
새 죽음 시각 포함):

| lang | 문구 (예: n=3, 17:44) |
|---|---|
| ko | `{skull} 3번째 소생 — 17시 44분에 또 죽어요` |
| en | `{skull} Revived 3× — dies again at 17:44` |
| ja | `{skull} 3回目の蘇生 — 17時44分にまた死にます` |
| zh | `{skull} 第3次复活 — 17点44分再次死亡` |

> 해골 뒤 공백은 1칸 (기존 `build_recap_message` 의 `🪦 Cache dies` 와 동일 스타일). regex 는 ping 의 `, N/M` 형태(`[cn:keepalive HH:MM, N/M]`)를 `[\s,](\d+)/\d+` 로 파싱.

set 예산 2줄째(`build_set_recap_line`)는 wake turn 에서도 동일 규칙(잔량>0)으로 뒤에 붙는다.

### 4.4 on_recap 흐름 (의사코드)

```
config = load_config(); style = config.display.recap_style
ttl 유효성 체크 (현행)
now, death_at = now + ttl
wake, n = detect_wake_turn(transcript_path)   # (bool, int)
if wake:
    line1 = build_revived_message(lang, n, death_at.hh, death_at.mm)
else:
    line1 = build_recap_message(lang, death_at.hh, death_at.mm)   # 현행
lines = [line1]
if marker.set_budget_remaining > 0:
    lines.append(build_set_recap_line(...))   # 현행
msg = render_box(lines) if style == "box" else "\n".join(lines)
print({"systemMessage": msg})
```

## 5. 컴포넌트 / 경계

| 파일 | 책임 | 의존 |
|---|---|---|
| `lib/box_render.py` (신규) | 표시폭 계산 + 박스 렌더. 순수 함수, 부수효과 0. | `unicodedata`(stdlib) |
| `lib/i18n.py` | `build_skull`, `build_revived_message` 추가 | 없음 |
| `lib/config.py` | `DisplayConfig(recap_style)` + `[display]` 파싱·검증·템플릿 | `tomllib` |
| `scripts/on_recap.py` | transcript wake 감지 + 라인 조립 + compact/box 렌더 | 위 3개 + marker |
| `config.toml.example` | `[display]` 섹션 문서화 | — |

안 건드림: `refresh.py`, `marker.py` 스키마, token-tracker, `/cn:status`.

## 6. 에러 핸들링

PRD 불변(어떤 실패도 chat 차단 X) 유지:

- transcript 읽기 실패/경로 없음/파싱 오류 ⇒ 일반 turn 으로 폴백, recap 은 정상 출력.
- `render_box` 입력이 빈 리스트 등 비정상 ⇒ on_recap 의 기존 try/except(silent fail) 가 흡수.
- `recap_style` 미지정/오타 ⇒ `compact` fallback + stderr 경고.
- on_recap 전체는 현행대로 `_main_impl` try/except 로 감싸 silent.

## 7. 테스트

- `tests/lib/test_box_render.py` — `display_width`: ASCII/CJK/🪦/☠️(VS16 포함)/혼합. `render_box`:
  1줄·2줄·CJK·이모지에서 모든 행의 총 폭이 `inner+2`(좌우 테두리) 로 동일한지(정렬 불변식).
- `tests/lib/test_i18n.py` — `build_skull`(n=1..5, 6, 10), `build_revived_message`(4 lang × 경계 시각).
- `tests/lib/test_config.py` — `[display] recap_style` 파싱: 미지정→compact, "box", 오타→compact+경고.
- `tests/scripts/test_on_recap.py` — 매트릭스: {compact,box} × {일반,wake} × {set 예산 유무}.
  wake 감지: keepalive transcript fixture 로 True, 일반 user 엔트리로 False, 파일 없음→False(폴백).
  N 파싱: `(3/5)`→3, 깨진 ping→1.

## 8. 구현 단계 (PR 분해)

프로덕션 코드 ~130줄 예상 → **1 PR**(세션-단위 기본, 300줄 이하).

1. `lib/box_render.py` + 테스트
2. `lib/config.py` `[display]` + 템플릿 + 테스트
3. `lib/i18n.py` skull/revived + 테스트
4. `scripts/on_recap.py` 통합(wake 감지 + 렌더) + 테스트
5. `config.toml.example` 갱신, 버전 0.6.0 bump (`pyproject.toml`, `plugin.json`), CHANGELOG

커지면 (1~2 = 박스) / (3~4 = 해골) 2 PR 로 분리.

## 9. 오픈 이슈 / 가정

- 박스 정렬은 **사용자 터미널이 monospace + 이모지 2칸 렌더**라는 가정에 의존한다. 일부 폰트는
  이모지를 1.5칸으로 그려 미세하게 어긋날 수 있음 — 알파 단계 허용 오차로 둔다.
- `transcript_path` 가 Stop payload 에 항상 포함된다고 가정(token-tracker on_stop 가 동일 사용). 누락
  시 일반 turn 폴백이라 안전.

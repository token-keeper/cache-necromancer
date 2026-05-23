# Cache Recap Message — Design (v0.3.12)

> Stop hook fire 시점에 사용자에게 "다음 wake 예정 시각" 을 Claude Code recap 영역(systemMessage) 으로 즉시 표시.

## 1. 목적

- 사용자가 prompt → Claude 응답 후 turn 종료 시점에 **다음 wake 시각을 명시적으로 인지**할 수 있도록 한다.
- 기존 PING (refresh_interval_minutes 만료 직전 wake) 와 **별개의 정보성 메시지** — wake 트리거 아님.
- mode 별 실제 동작과 일치하는 정확한 안내 (auto/hybrid 는 wake, notify 는 알림만, no-op 케이스는 그대로).

## 2. 범위

### 포함
- Stop hook fire 시점 즉시 systemMessage 출력 (sync hook 신규)
- HH:MM = `fire_time + config.refresh_interval_minutes` (KST) — **wake 시도 시각** (cache 만료 시각 ≠)
- max_refresh_count 도달 시 메시지 분기
- mode 별 메시지 분기 (auto/hybrid/notify + system_notification true/false)

### 제외 (YAGNI)
- 메시지 ON/OFF config key (항상 ON)
- 메시지 형식 커스터마이즈
- 다국어 (한글 고정)
- 별도 알림 채널 (osascript 등) — 기존 notify mode 의 osascript 와 중복
- config.py 의 타입/범위 검증 추가 — 별도 PR scope (이번 PR 은 on_recap.py 내부 가드만)

## 3. 메커니즘

### 3.1 hooks.json 구조

Stop 배열에 hook 객체 **2개** 등록 (배열 순서 = 실행 순서):

```json
{
  "hooks": {
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
  }
}
```

- **on_recap.py (sync, timeout 5s)** — stdout systemMessage 즉시 출력, exit 0
- **refresh.py (async, timeout 1h)** — 기존 그대로 (sleep + wake)

### 3.2 검증 출처 + 수동 검증 절차

**검증 근거** (claude-code-guide subagent 답변, 출처 [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks.md) — Hook Lifecycle Events, Configuration Structure, Async Hooks):
- Stop 배열 객체 2개 → 배열 순서대로 순차 실행
- `asyncRewake: true` 는 해당 hook 만 background 로 실행 → 다른 sync hook 의 실행 막지 않음
- 동시 진행 가능

**구현 후 수동 검증 절차 (PR 머지 전 필수)**:
1. test 세션에서 prompt 1회 입력 + Claude 응답 받기
2. turn 종료 즉시 chat UI 의 systemMessage 영역에 "🪦 캐시는 HH:MM 에 살리러 갈게요! (KST)" 표시 확인
3. ~50분 후 기존 PING (`[cn:keepalive ...]` → `ok @HH:MM (N/M)`) 정상 동작 확인
4. log 파일 (`cn.log`) 에서 on_recap.py + refresh.py 둘 다 실행됐는지 확인
5. `/cn:status` 결과에서 wake_count, latest_fire 정상 갱신 확인

### 3.3 systemMessage JSON 형식

**mode 별 분기**:

| mode | system_notification | 메시지 |
|------|--------------------:|--------|
| auto | (무관) | `🪦 캐시는 HH:MM KST 에 살리러 갈게요!` |
| hybrid | true | `🪦 캐시는 HH:MM KST 에 살리러 갈게요!` |
| hybrid | false | `🪦 캐시는 HH:MM KST 에 살리러 갈게요!` (auto 와 동일) |
| notify | true | `🪦 캐시는 HH:MM KST 에 만료 임박, 알림만 갑니다. 직접 돌아오세요.` |
| notify | false | `🪦 캐시는 HH:MM KST 에 만료 임박. 자동 wake/알림 없음 — 직접 재진입 필요.` |

max_refresh_count 도달 시 (mode 무관):
```
🪦 캐시는 HH:MM KST 에 만료 임박. 자동 살림 한도 도달 — 유지하려면 직접 메시지를 보내세요.
```

**JSON 출력**:
```python
print(json.dumps({"systemMessage": message}, ensure_ascii=False))
```

`ensure_ascii=False` 명시 — 한글/emoji 깨짐 방지.

### 3.4 silent fail (PRD 불변)

**top-level try/except 보장**:
```python
def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        # PRD 불변 — 어떤 예외도 chat 동작 차단 X
        try:
            log_warn(f"[on_recap] 예외 silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0
```

silent fail 케이스:
- config 로드 실패 → stdout empty + exit 0
- stdin session_id 없음 → stdout empty + exit 0
- marker 로드 실패 → max_count 미확인, 정상 메시지 출력 (best-effort)
- `refresh_interval_minutes` 가 int 아니거나 ≤ 0 → stdout empty + exit 0
- `datetime` / `json.dumps` / `print` 등 예상 밖 예외 → top-level 캐치 + stdout empty + exit 0

## 4. 파일 변경

### 4.1 신규
- `scripts/on_recap.py` — sync hook 본체
- `tests/scripts/test_on_recap.py` — pytest 케이스

### 4.2 기존 수정
- `hooks/hooks.json` — Stop 배열에 sync hook 추가만 (기존 async hook 유지)

### 4.3 변경 없음
- `lib/config.py`, `lib/marker.py`, `lib/notify.py`, `lib/logger.py`
- `scripts/refresh.py`, `scripts/on_user_prompt.py`, `scripts/on_session_end.py`
- `scripts/on_status_command.py`, `scripts/cn_status.py`

## 5. on_recap.py 의사코드

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

    # auto / hybrid → wake
    return f"🪦 캐시는 {death_hhmm} KST 에 살리러 갈게요!"


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

    # interval 가드 (config.py 미검증 대비)
    interval = config.refresh_interval_minutes
    if not isinstance(interval, int) or interval <= 0:
        return 0

    # HH:MM 계산
    death_at = datetime.now(_KST) + timedelta(minutes=interval)
    death_hhmm = death_at.strftime("%H:%M")

    # marker load — max_count 도달 여부
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


def main() -> int:
    try:
        return _main_impl()
    except Exception as e:
        try:
            log_warn(f"[on_recap] 예외 silent fail: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 0
```

## 6. test 케이스

`tests/scripts/test_on_recap.py`:

### 6.1 정상 동작
1. **auto mode 정상** — interval=50, fire_time=10:00 → "🪦 캐시는 10:50 KST 에 살리러 갈게요!"
2. **hybrid mode 정상** — auto 와 동일 메시지
3. **자정 넘김** — fire_time=23:55, interval=30 → "🪦 캐시는 00:25 KST 에 ..."
4. **notify mode + system_notification=true** → "알림만 갑니다, 직접 돌아오세요."
5. **notify mode + system_notification=false** → "자동 wake/알림 없음 — 직접 재진입 필요."

### 6.2 max_count 분기
6. **max_count 도달 (auto)** — wake_count=10, max=10 → "한도 도달 — 유지하려면 직접 메시지를..."
7. **max_count 도달 (notify)** — mode 무관 동일 메시지

### 6.3 silent fail
8. **config 로드 실패** → stdout empty, exit 0
9. **session_id 없음** → stdout empty, exit 0
10. **marker 로드 실패** → 정상 메시지 출력 (maxed_out=False)
11. **interval=0** → stdout empty, exit 0
12. **interval=음수** → stdout empty, exit 0
13. **interval=문자열** → stdout empty, exit 0
14. **top-level 예외 (mocked `datetime.now` raise)** → stdout empty, exit 0

### 6.4 JSON / 형식
15. **systemMessage JSON 파싱 가능** — `json.loads(stdout)["systemMessage"]` 성공
16. **ensure_ascii=False** — emoji 🪦 raw 출력 (escape X)

### 6.5 hooks.json 구조 검증
17. **hooks.json 구조** — Stop 배열에 객체 2개, 첫번째 = on_recap.py (sync), 두번째 = refresh.py (asyncRewake=true)
18. **기존 refresh.py 등록 불변** — command 경로, asyncRewake=true, timeout=3600 그대로

### 6.6 기존 동작 회귀
19. **기존 PING 문자열 불변** — refresh.py 의 `_build_ping` 출력 형식 변경 없음 (regression guard)

## 7. 마일스톤 위치

- **v0.3.12 (별도 PR)** — B/C 와 의존성 X, 독립적 small fix
- v0.4.0 마일스톤 (B `/cn:set` + C `setup.py`) 과 분리
- 이유: 작고 독립적이므로 v0.4.0 대기 X, 먼저 머지 가능

## 8. 영향도

- pytest baseline: 131 → ~150 (신규 케이스 19개)
- 기존 동작 변경 없음 (refresh.py 무수정)
- hooks.json Stop 배열만 추가 (기존 hook 그대로)
- 신규 의존성 없음

## 9. 결정 기록

- **systemMessage 채널 선택 이유**: Stop hook 공식 JSON 결과 필드 중 UI 시스템 메시지 영역 표시 보장. additionalContext (다음 turn inject) / terminalSequence (OSC) 보다 사용자 의도 "recap 영역 즉시 표시" 와 일치
- **sync + async hook 분리 이유**: asyncRewake true 모드에서 stdout 캡처 타이밍 불확정. sync hook 으로 분리하면 turn 종료 즉시 stdout 캡처 보장
- **메시지 표현 ("살리러 갈게요")**: `fire_time + refresh_interval_minutes` = wake 시도 시각. cache 실제 TTL (1h 가정) 만료 직전 wake. "죽습니다" 표현은 wake 시각 = 만료 시각 오해 유발 → "살리러 갈게요" 로 wake 시각 명확화
- **mode 별 메시지 분기 이유**: 메시지 정확성. notify mode 또는 system_notification=false 에서 "제가 살려놓을게요!" 는 거짓. mode 별 실제 동작과 메시지 일치 필수
- **max_count 분기 이유**: wake 안 일어나는 상황을 사용자가 알아야 cache 만료 시 직접 chat 으로 돌아갈지 결정 가능. 액션 안내 ("직접 메시지를 보내세요") 포함
- **silent fail top-level 보장**: PRD 불변 — hook 이 chat 동작 절대 차단 X. 의사코드 일부 try/except 만으로는 부족. `main()` 전체 wrap
- **interval 가드**: config.py 검증 미흡 보완. recap hook 만 가드, config.py 자체 검증은 별도 PR
- **emoji `🪦` 사용**: 사용자 명시 승인. `json.dumps(ensure_ascii=False)` 로 raw 출력
- **KST suffix**: 사용자 timezone 오해 방지. 기존 PING 도 KST hardcode 와 일관
- **config 신규 key 없음**: YAGNI. 향후 사용자 피드백에 따라 v0.4.x 에서 추가 가능

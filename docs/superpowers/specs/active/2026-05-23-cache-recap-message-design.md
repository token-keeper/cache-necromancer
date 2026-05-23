# Cache Recap Message — Design (v0.3.12 또는 v0.4.x)

> Stop hook fire 시점에 사용자에게 "캐시 만료 예정 시각" 을 Claude Code recap 영역(systemMessage) 으로 즉시 표시.

## 1. 목적

- 사용자가 prompt → Claude 응답 후 turn 종료 시점에 **캐시 만료 시각을 명시적으로 인지**할 수 있도록 한다.
- 기존 PING (refresh_interval_minutes 만료 직전 wake) 와 **별개의 정보성 메시지** — wake 트리거 아님.
- "캐시는 HH:MM 에 죽습니다. 제가 살려놓을게요!" 형식으로 친근하게 표시 (필요 시 max_count 도달 안내 분기).

## 2. 범위

### 포함
- Stop hook fire 시점 즉시 systemMessage 출력 (sync hook 신규)
- HH:MM = `fire_time + config.refresh_interval_minutes` (KST)
- max_refresh_count 도달 시 메시지 분기

### 제외 (YAGNI)
- 메시지 ON/OFF config key (항상 ON)
- 메시지 형식 커스터마이즈
- 다국어 (한글 고정)
- 별도 알림 채널 (osascript 등) — 기존 notify mode 의 osascript 와 중복

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

검증된 사실:
- `asyncRewake: true` hook 은 background 진입 → 후속 sync hook 의 실행 막지 않음
- Stop 배열 객체 2개 → 순차 실행 (sync 완료 후 async 시작)
- asyncRewake 모드에서 stdout JSON 캡처 타이밍 불확정 → sync hook 분리 필수

### 3.2 systemMessage JSON 형식

기본 (정상):
```json
{"systemMessage": "🪦 캐시는 HH:MM 에 죽습니다. 제가 살려놓을게요!"}
```

max_refresh_count 도달 시:
```json
{"systemMessage": "🪦 캐시는 HH:MM 에 죽습니다. (자동 살림 한도 도달 — wake X)"}
```

emoji `🪦` (무덤) prefix 사용자 명시 승인. 모든 메시지에 prefix.

### 3.3 silent fail (PRD 불변)

- config 로드 실패 → stdout empty + exit 0
- stdin session_id 없음 → stdout empty + exit 0
- marker 로드 실패 → max_count 미확인으로 간주, 정상 메시지 출력
- 어떤 예외도 chat 동작 차단 X (PRD 불변 유지)

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
def main() -> int:
    sid = _resolve_session_id()  # stdin 우선, env fallback
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
        return 0  # silent fail

    # HH:MM 계산
    fire_at = datetime.now(_KST)
    death_at = fire_at + timedelta(minutes=config.refresh_interval_minutes)
    death_hhmm = death_at.strftime("%H:%M")

    # marker load — max_count 도달 여부 확인
    try:
        marker = Marker.load(sid_hash)
        maxed_out = marker.wake_count >= config.max_refresh_count
    except OSError:
        maxed_out = False

    if maxed_out:
        message = (
            f"🪦 캐시는 {death_hhmm} 에 죽습니다. "
            "(자동 살림 한도 도달 — wake X)"
        )
    else:
        message = (
            f"🪦 캐시는 {death_hhmm} 에 죽습니다. "
            "제가 살려놓을게요!"
        )

    print(json.dumps({"systemMessage": message}))
    return 0
```

## 6. test 케이스

`tests/scripts/test_on_recap.py`:

1. **정상 case** — refresh_interval_minutes=50, fire_time=10:00 → "🪦 캐시는 10:50 에 죽습니다. 제가 살려놓을게요!"
2. **자정 넘김** — fire_time=23:55, interval=30 → "🪦 캐시는 00:25 에 죽습니다. ..."
3. **max_count 도달** — wake_count=10, max=10 → "한도 도달" 메시지
4. **config 로드 실패** → stdout empty, exit 0
5. **session_id 없음** → stdout empty, exit 0
6. **marker 로드 실패** → 정상 메시지 출력 (maxed_out=False)
7. **systemMessage JSON 형식** — `json.loads(stdout)` 성공 + key="systemMessage"

## 7. 마일스톤 위치

- **v0.3.12 (별도 PR)** — B/C 와 의존성 X, 독립적 small fix
- v0.4.0 마일스톤 (B `/cn:set` + C `setup.py`) 과 분리
- 이유: 작고 독립적이므로 v0.4.0 대기 X, 먼저 머지 가능

## 8. 영향도

- pytest baseline: 131 → ~138 (신규 케이스 7개)
- 기존 동작 변경 없음 (refresh.py 무수정)
- hooks.json Stop 배열만 추가 (기존 hook 그대로)

## 9. 결정 기록

- **systemMessage 채널 선택 이유**: Stop hook 공식 JSON 결과 필드 중 UI 시스템 메시지 영역 표시 보장. additionalContext (다음 turn inject) / terminalSequence (OSC) 보다 사용자 의도 "recap 영역 즉시 표시" 와 일치
- **sync + async hook 분리 이유**: asyncRewake true 모드에서 stdout 캡처 타이밍 불확정. sync hook 으로 분리하면 turn 종료 즉시 stdout 캡처 보장
- **max_count 분기 이유**: wake 안 일어나는 상황을 사용자가 알아야 cache 만료 시 직접 chat 으로 돌아갈지 결정 가능
- **config 신규 key 없음**: YAGNI. 향후 사용자 피드백에 따라 v0.4.x 에서 추가 가능

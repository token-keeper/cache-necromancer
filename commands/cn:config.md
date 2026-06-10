---
description: cache-necromancer 설정 변경 (인터랙티브)
allowed-tools: AskUserQuestion, Read, Edit, Write
---

cache-necromancer 의 `~/.cache-necromancer/config.toml` 을 인터랙티브로 변경한다. 4개 설정 항목을 한 번에 질문하며, 현재값은 옵션 라벨에 `✓ ` prefix 로 표시한다. 각 질문에는 후보 외 자유 입력을 위한 `Type something` 옵션이 자동 제공된다.

## 절차

### 1. 현재 설정 읽기

`Read` 로 `~/.cache-necromancer/config.toml` 을 읽어 다음 4개 키의 현재값을 메모리에 보관:

- `[wake].arm`
- `[notify].enabled`
- `[general].refresh_interval_minutes`
- `[general].max_refresh_count`

파일이 없으면 기본값 가정: `manual` / `true` / `50` / `10`. (v0.5.0 default)

### 2. AskUserQuestion 호출 (4개 질문 한 번에)

`AskUserQuestion` 한 번 호출에 아래 4개 질문을 묶어 보낸다 (multiSelect=false). 각 질문의 현재값에 해당하는 옵션 라벨 앞에 `✓ ` prefix 를 붙인다.

**Q1: Wake arm**
- question: `"wake.arm 을 선택하세요 (현재: <현재값>)"`
- options (2개):
  - `manual` — /cn:set 충전분만 소생, 알림은 계속 (기본)
  - `always` — 매 turn 자동 arm — 깜빡 보호, wake 비용 발생

**Q2: Notify enabled**
- question: `"notify.enabled 를 선택하세요 (현재: <현재값>) — macOS 알림 활성 여부"`
- options (2개):
  - `true` — 알림 활성 (기본)
  - `false` — 알림 끔

**Q3: Interval**
- question: `"refresh_interval_minutes 를 선택하세요 (현재: <현재값>분) — cache TTL 만료 직전 알림/wake 까지의 sleep"`
- options (4개):
  - `2` — 테스트용
  - `30` — 빠른 갱신
  - `50` — 기본값 (1h cache 기준 안전 마진)
  - `90` — 느린 갱신 (cache 만료 위험 ↑)

**Q4: Max count**
- question: `"max_refresh_count 를 선택하세요 (현재: <현재값>) — wake 상한 (always 연쇄 상한 / set 1회 충전 상한)"`
- options (4개):
  - `5` — 보수적 (비용 최소화)
  - `10` — 기본값
  - `20` — 여유 있음
  - `50` — 거의 무제한

### 3. 답변값 정규화

각 답변에서 `✓ ` prefix 와 공백을 strip 하여 순수 값만 추출 (`✓ manual` → `manual`). 사용자가 `Type something` 으로 자유 입력한 경우엔 strip 없이 입력값 그대로 사용.

`notify.enabled` 답변은 `true` / `false` 문자열을 그대로 TOML boolean 으로 작성한다 (따옴표 없음).

### 4. config.toml 갱신

각 키별로 현재값과 답변값을 비교하여 변경된 항목만 반영:

- **파일이 있는 경우**: `Edit` 으로 해당 키 라인만 갱신:
  - `arm = "<현재값>"` → `arm = "<새값>"`
  - `enabled = <현재값>` → `enabled = <새값>`
  - `refresh_interval_minutes = <현재값>` → `refresh_interval_minutes = <새값>`
  - `max_refresh_count = <현재값>` → `max_refresh_count = <새값>`
- **파일이 없는 경우**: `Write` 로 아래 v0.5.0 기본 템플릿에 4개 선택값 반영 후 생성:

```toml
# cache-necromancer 설정 — /cn:config 로 변경 가능
[general]
refresh_interval_minutes = <선택값>
cache_ttl_minutes = 60
max_refresh_count = <선택값>
language = "en"

[notify]
enabled = <선택값>

[wake]
arm = "<선택값>"
grace_seconds = 60
```

- **4개 모두 그대로**: 갱신 안 함 (Edit/Write 호출 모두 생략).

### 5. 적용 시점 안내

v0.5.0 config 는 매 hook fire 시 다시 읽힘 → **다음 Stop hook 발화 시 자동 적용**. 단:

- `refresh_interval_minutes` 변경: 이미 sleep 중인 refresh.py 프로세스에는 영향 X. 다음 사이클부터 적용.
- `wake.arm` / `notify.enabled` 변경: 동일.
- 그 외 (`max_refresh_count`): 동일.

별도 명령 실행 불필요.

### 6. 완료 보고

- **변경 없음**: `"변경 사항 없음 (4개 키 모두 그대로)"`
- **변경 있음**: 변경된 각 키마다 한 줄씩 `"✓ <key> <이전>→<새값>"` 보고. 마지막에 한 줄:
  - `"다음 Stop hook 발화부터 자동 적용. 별도 재시작 불필요."`

## 주의

- 사용자가 `~/.cache-necromancer/config.toml` 의 다른 키 (예: `[wake].grace_seconds`) 를 직접 편집한 경우, 그 값을 보존해야 한다. `Edit` 도구로 *해당 키 라인만* 갱신한다 (전체 덮어쓰기 금지).
- v0.4.x legacy 키 (`[general].mode`, `[notify].system_notification`, `[refresh].hybrid_wait_seconds`) 는 로드 시 자동 매핑되므로 기존 설정 파일도 그대로 동작한다. `/cn:status` 에서 legacy 키 사용 경고가 표시되면 해당 키를 신 키로 교체하는 것을 권장. 단 `/cn:config` 는 신 키(`arm`, `enabled`)로 기록하므로 파일이 없을 때 자동 생성 시 legacy 키 포함 안 함.
- v0.2.x 잔재 deprecated 키 (`[refresh].prompt`, `[notify].terminal_bell`, `[notify].imminent_threshold_minutes`, `[refresh].fire_timeout_seconds`, `[advanced].*`) 는 v0.3.0 에서 폐기, 무시됨. 그 값을 보존해야 할 경우 Edit 도구로 해당 라인 외 손대지 않는다 (전체 덮어쓰기 금지).
- `[wake].grace_seconds` 는 알림 후 wake 까지의 대기 시간 (default 60s). 자주 바꾸지 않는 advanced 설정이라 /cn:config 에서 제외. 변경이 필요하면 `~/.cache-necromancer/config.toml` 의 `[wake].grace_seconds` 를 직접 편집.
- v0.3.0+ 에서 daemon 자체가 폐기되었으므로 `pkill` / `daemon.lock` 정리 등은 불필요.

---
description: cache-necromancer 설정 변경 (인터랙티브)
allowed-tools: AskUserQuestion, Read, Edit, Write, Bash(pkill:*), Bash(rm:*), Bash(ls:*)
---

cache-necromancer 의 `~/.cache-necromancer/config.toml` 을 인터랙티브로 변경한다. 4개 설정 항목을 한 번에 질문하며, 현재값은 옵션 라벨에 `✓ ` prefix 로 표시한다. 각 질문에는 후보 외 자유 입력을 위한 `Type something` 옵션이 자동 제공된다.

## 절차

### 1. 현재 설정 읽기

`Read` 로 `~/.cache-necromancer/config.toml` 을 읽어 다음 4개 키의 현재값을 메모리에 보관:

- `[general].mode`
- `[general].refresh_interval_minutes`
- `[general].max_refresh_count`
- `[notify].imminent_threshold_minutes`

파일이 없으면 기본값 가정: `hybrid` / `55` / `10` / `5`.

### 2. AskUserQuestion 호출 (4개 질문 한 번에)

`AskUserQuestion` 한 번 호출에 아래 4개 질문을 묶어 보낸다 (multiSelect=false). 각 질문의 현재값에 해당하는 옵션 라벨 앞에 `✓ ` prefix 를 붙인다.

**Q1: Mode**
- question: `"mode 를 선택하세요 (현재: <현재값>)"`
- options (3개):
  - `notify` — 알림만 (fire 없음, 비용 0)
  - `auto` — 자동 fire (무인 자동화)
  - `hybrid` — 60초 사전 알림 후 fire (취소 가능)

**Q2: Interval**
- question: `"refresh_interval 을 선택하세요 (현재: <현재값>분)"`
- options (4개):
  - `2` — 테스트용
  - `30` — 빠른 갱신
  - `55` — 기본값
  - `120` — 느린 갱신

**Q3: Max count**
- question: `"max_refresh_count 를 선택하세요 (현재: <현재값>) — 세션당 최대 갱신 횟수, 비용 상한"`
- options (4개):
  - `5` — 보수적 (비용 최소화)
  - `10` — 기본값
  - `20` — 여유 있음
  - `50` — 거의 무제한

**Q4: Imminent**
- question: `"imminent_threshold_minutes 를 선택하세요 (현재: <현재값>분) — 다음 fire N분 전에 임박 알림"`
- options (4개):
  - `1` — 직전 알림
  - `3` — 짧은 사전 알림
  - `5` — 기본값
  - `10` — 여유 있는 사전 알림

### 3. 답변값 정규화

각 답변에서 `✓ ` prefix 와 공백을 strip 하여 순수 값만 추출 (`✓ hybrid` → `hybrid`). 사용자가 `Type something` 으로 자유 입력한 경우엔 strip 없이 입력값 그대로 사용.

### 4. config.toml 갱신

각 키별로 현재값과 답변값을 비교하여 변경된 항목만 반영:

- **파일이 있는 경우**: `Edit` 으로 해당 키 라인만 갱신:
  - `mode = "<현재값>"` → `mode = "<새값>"`
  - `refresh_interval_minutes = <현재값>` → `refresh_interval_minutes = <새값>`
  - `max_refresh_count = <현재값>` → `max_refresh_count = <새값>`
  - `imminent_threshold_minutes = <현재값>` → `imminent_threshold_minutes = <새값>`
- **파일이 없는 경우**: `Write` 로 아래 템플릿에 4개 선택값 반영 후 생성:

```toml
# cache-necromancer 설정 — /cn:config 로 변경 가능
[general]
mode = "<선택값>"
refresh_interval_minutes = <선택값>
max_refresh_count = <선택값>

[refresh]
prompt = "."
hybrid_wait_seconds = 60
fire_timeout_seconds = 120

[notify]
terminal_bell = true
system_notification = true
imminent_threshold_minutes = <선택값>
```

- **4개 모두 그대로**: 갱신 안 함 (Edit/Write 호출 모두 생략).

### 5. 데몬 재시작 (refresh_interval_minutes 외 어떤 키라도 변경된 경우)

`refresh_interval_minutes` 는 Stop hook 이 매번 reload 하므로 단독 변경 시 데몬 재시작 불필요. **그 외 3개 키 (`mode`, `max_refresh_count`, `imminent_threshold_minutes`) 중 어느 하나라도 변경된 경우 데몬 재시작 필요**.

`Bash` 로 실행:

```bash
pkill -f "python.*-m daemon" 2>/dev/null; rm -f ~/.cache-necromancer/daemon.lock; true
```

다음 Stop hook 이 새 데몬을 spawn 하면서 갱신된 config 가 적용된다.

### 6. 완료 보고

- **변경 없음**: `"변경 사항 없음 (4개 키 모두 그대로)"`
- **변경 있음**: 변경된 각 키마다 한 줄씩 `"✓ <key> <이전>→<새값>"` 보고. 마지막에 데몬 재시작 여부 한 줄 추가:
  - 재시작한 경우: `"데몬 재시작됨. 다음 응답부터 적용."`
  - 재시작 안 한 경우 (refresh_interval 만 변경): `"데몬 재시작 불필요. 다음 Stop hook 부터 적용."`

## 주의

- 사용자가 `~/.cache-necromancer/config.toml` 의 다른 키 (예: `[refresh].prompt`, `[refresh].hybrid_wait_seconds`, `[notify].terminal_bell`, `[advanced].*`) 를 직접 편집한 경우, 그 값을 보존해야 한다. `Edit` 도구로 *해당 키 라인만* 갱신한다 (전체 덮어쓰기 금지).
- 데몬 재시작 명령은 plugin 외부 프로세스를 종료한다. 위 3개 키가 안 바뀐 경우엔 실행하지 않는다 (불필요한 부작용 방지).
- `refresh_prompt` 키는 자주 바꾸지 않는 advanced 설정이라 /cn:config 에서 제외. 변경이 필요하면 `~/.cache-necromancer/config.toml` 의 `[refresh].prompt` 를 직접 편집.

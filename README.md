<div align="center">

![cache-necromancer banner](docs/assets/banner.png)

# cache-necromancer

> **Claude Code 1시간 프롬프트 캐시 만료 직전에 자동으로 캐시를 살리는 macOS 플러그인.**

![status](https://img.shields.io/badge/status-alpha-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![platform](https://img.shields.io/badge/platform-macOS-lightgrey)

</div>

---

## 무엇이 문제인가

Claude Code 캐시 TTL = 1h. 그 안에 다음 요청 → cache_read 비용 (정상의 10%). 만료 후 → 전체 cache_create 비용 (×10).

자리 비움 50분 → 다시 작업 → 비용 ×10.

## 어떻게 동작하는가

매 turn 끝마다 `Stop` hook + `asyncRewake` 로 background sleep. 50분 동안 user input 없으면 chat 세션이 자기 자신을 wake (짧은 ping → 모델 `ok` 1 token).

chat 프로세스 내부 wake → system prompt + tools byte-exact 보존 → **cache prefix 100% hit**. wake 비용 ≤ $0.10.

## 설치

```bash
/plugin marketplace add token-keeper/plugins
/plugin install cache-necromancer@token-keeper
```

설치 후 **새 chat 세션** 부터 적용 (Claude Code settings hot-reload 안 함).

## 작동 모드

`~/.cache-necromancer/config.toml` (첫 hook fire 시 자동 생성):

| mode | 동작 |
|------|------|
| `notify` | 50분 후 macOS 알림만 (wake X) |
| `auto` | 50분 후 자동 wake |
| `hybrid` (기본) | 알림 → 60s 안에 input 없으면 wake |

```toml
[general]
mode = "hybrid"
refresh_interval_minutes = 50         # wake 주기
cache_ttl_minutes = 60                # recap 메시지 시각용
max_refresh_count = 10                # 세션당 최대 wake 횟수
language = "en"                       # ko | en | ja | zh

[notify]
system_notification = true

[refresh]
hybrid_wait_seconds = 60
```

## Recap 메시지

매 turn 종료 직후 cache 만료 시각 표시:

```
Stop says: 🪦 Cache dies at 09:37.
```

`language` 4종: `ko` / `en` / `ja` / `zh`. 시각 = `now + cache_ttl_minutes`, 사용자 시스템 local time.

## 슬래시 명령

| 명령 | 설명 |
|---|---|
| `/cn:config` | 모드 변경 |
| `/cn:status` | 세션 상태 + 다음 발동 예상 (API 비용 0) |

Wake 발생 시 transcript:

```
[cn:keepalive 16:42, 3/10] reply with exactly 'ok @16:42 (3/10)'. ...
ok @16:42 (3/10)
```

## 안전성

- **Silent fail**: 모든 hook silent (exit 0). chat 동작 차단 X.
- **민감정보 미기록**: log = `sid_hash` + token 수만. 본문 기록 X. 7일 자동 회전.
- **권한**: marker file 0600 / dir 0700.
- **Atomic write**: `tempfile + os.replace()`.

## 비추천 / 주의

- 공식 권장 패턴 아님 (Anthropic 캐시 정책 회색지대). 개인 사용 목적.
- 매 wake = minimal turn 비용 발생.
- wake-up turn (`ok @HH:MM`) 은 영구 transcript 기록.

## 파일 위치

```
~/.cache-necromancer/
├── cn.log.YYYY-MM-DD       # sid_hash + token만
├── config.toml
└── marker/<sid_hash>.json
```

## 개발

```bash
uv venv && uv sync --extra dev
uv run pytest
```

## 라이선스

MIT — `LICENSE` 참조.

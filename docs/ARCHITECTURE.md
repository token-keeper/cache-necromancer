# cache-necromancer 구조 (v0.11.0)

> 독자: 이 repo 를 고치는 사람. 기준: v0.11.0 코드 (`hooks/`·`scripts/`·`lib/`). 변경 이력은 [CHANGELOG](../CHANGELOG.md).

## 구성요소

| 구성요소 | 위치 | 하는 일 |
|---|---|---|
| mod | `hooks/register.tsx` (`hooks.json` 의 `modules`) | 프롬프트 위 띠(카운트다운·10분 구간 6단계 색·뒤 정보: 살린 횟수·목숨·예산과 생존 시각), 경고·만료 토스트, 1초 tick 의 깨우기 타이머 |
| Stop 훅 | `scripts/on_recap.py` | `marker.latest_fire`(마지막 Stop 시각) 기록, config.toml 없으면 기본 템플릿 생성. 출력 없음 |
| UserPromptSubmit 훅 | `scripts/on_user_prompt.py` | 진짜 사용자 입력이면 `wake_count` 0·`last_user_activity_at_ns` 갱신, 복귀 판정 시 `/cn:set` 예산 소멸. ping·`<task-notification>`·`/cn:*` 는 활동으로 안 셈 |
| SessionStart 훅 (`clear\|compact`) | `scripts/on_session_start.py` | `suppressed_at_ns` 기록 — 다음 진짜 입력 전까지 깨우기·알림 억제 |
| SessionEnd 훅 (async) | `scripts/on_session_end.py` | 이 세션 marker 삭제 + 7일 넘은 marker 정리 |
| UserPromptExpansion 훅 | `scripts/on_status_command.py` | `/cn:status`·`/cn:set`·`/cn:config` 를 LLM turn 없이 처리 (`cn_status.py`·`cn_set.py`·`cn_config.py`) |
| 깨우기 판정 | `scripts/refresh.py --now` | mod 가 실행. 재확인(세션 종료·사용자 활동·억제) → arm/예산 분기 → 알림 → grace 대기·재확인 → 예산 차감·`wake_count` 증가 → stderr 에 ping 쓰고 exit 2 |

## 깨우기 흐름

```
turn.step (메인 대화, 캐시 read+creation > 0)
  └─ base = 그 요청의 시작 시각           ← mod atom
1초 tick
  ├─ 띠·토스트 갱신 (base + cache_ttl_minutes 까지 남은 시간)
  └─ refresh_interval ≤ now - base < cache_ttl 이고 이 base 로 아직 안 깨웠으면
       └─ refresh.py --now  (stdin: session_id, 상한 10분)
            ├─ exit 0 → 끝 (알림만 했거나 건너뜀)
            └─ exit 2 → stderr 의 [cn:keepalive 줄만 prompt.submit
                          └─ ping turn 이 캐시를 읽음 → turn.step 이 base 갱신 → 다음 주기 (연쇄)
```

- 연쇄 상한: `arm = "always"` 는 `max_refresh_count`, `arm = "manual"` 은 `/cn:set N` 예산.
- 마지막 Stop 뒤 사용자 입력이 있으면(turn 진행 중이거나 이미 돌아옴) Python 이 건너뛴다.

## 상태 저장소

| 저장소 | 쓰는 쪽 | 내용 |
|---|---|---|
| mod atom (세션 메모리) | mod 만 | `base`, 띠 `label`, `config`, 토스트·깨우기 1회 가드(`warnedFor`·`expiredFor`·`wokeFor`), 읽어 둔 `marker` |
| `~/.cache-necromancer/marker/<sid>.json` | **Python 만** | `latest_fire`, `wake_count`, `last_user_activity_at_ns`, `suppressed_at_ns`, `set_budget_remaining`·`set_budget_total`·`set_charged_at_ns` |
| `~/.cache-necromancer/config.toml` | 사용자·`/cn:config`·Python(템플릿 생성) | 설정 |
| `~/.cache-necromancer/cn.log.YYYY-MM-DD` | Python (`lib/logger.py`) | `[refresh]` 등 판정 로그 |

mod 는 marker 를 5초 간격·깨우기 직후에 **읽기만** 한다. 경로 루트는 모두 `$CN_ROOT` 가 있으면 그것.

## 설정 반영 시점

- mod: 세션 시작(`session.start`) 때, 또는 리로드 뒤 첫 tick 에 읽는다 → 띠·깨우기 시점(`cache_ttl_minutes`·`refresh_interval_minutes`·`countdown`·`language`, 뒤 정보용 `arm`·`max_refresh_count`·`notify`·`grace`)은 새 세션 또는 `/reload-plugins` 뒤부터.
- Python: 실행마다 읽는다 → 깨우기 판정(`arm`·`max_refresh_count`·`notify`·`grace` 등)은 다음 판정부터.

## 알려진 제약

- mods 는 Claude Code v2.1.286 이상. 그 미만은 `modules` 를 무시해 띠·알림·깨우기가 없고 Python 훅·`/cn:*` 만 동작한다.
- `/reload-plugins` 뒤 `session.start` 가 안 올 수 있다 — 0.11.0 부터 `ui.render`·`turn.step` 중 먼저 오는 쪽에서 타이머를 건다. settings 훅(`hooks.json`)의 경로는 여전히 재시작해야 바뀐다 ([CLAUDE.md](../CLAUDE.md)).
- Esc 로 중단한 turn 은 Stop 이 없어 다음 완료 turn 까지 깨우지 않는다.
- Claude Code 재시작은 SessionEnd 로 marker 를 지워 `/cn:set` 예산이 사라진다 (resume 후 다시 충전).
- grace 가 약 9분 30초를 넘으면 `refresh.py --now` 가 mod 의 10분 상한에 걸린다.

실측 기록: 2026-10-07 깨우기 1회 cache_read 355,998 / creation 271

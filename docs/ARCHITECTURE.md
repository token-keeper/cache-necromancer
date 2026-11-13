# cache-necromancer 구조 (v0.12.0)

> 독자: 이 repo 를 고치는 사람. 기준: v0.12.0 코드 (`hooks/`·`scripts/`·`lib/`). 변경 이력은 [CHANGELOG](../CHANGELOG.md).

## 구성요소

| 구성요소 | 위치 | 하는 일 |
|---|---|---|
| mod | `hooks/register.tsx` (`hooks.json` 의 `modules`) | 입력창 아래 띠(`PromptHint` 자리, 엔진 힌트 줄 위 — 카운트다운·10분 구간 6단계 색·뒤 정보: 살린 횟수·남은 깨우기 또는 깨우기 꺼짐과 생존 시각), 경고·만료 토스트, 1초 tick 의 깨우기 타이머, `/cn:set` 충전 시 재판정 |
| Stop·StopFailure 훅 | `scripts/on_recap.py` | `marker.latest_fire`(마지막 turn 끝 시각) 기록 — API 오류로 끝난 turn(`StopFailure`)도 같게 기록해 진행 중 turn 판정이 풀린다. config.toml 없으면 기본 템플릿 생성. 출력 없음 |
| UserPromptSubmit 훅 | `scripts/on_user_prompt.py` | ping·`/cn:*` 를 뺀 모든 프롬프트에 `last_turn_start_at_ns`(turn 시작) 기록. 그중 진짜 사용자 입력이면 `wake_count` 0·`last_user_activity_at_ns` 갱신(깨운 적 있으면 `[return]` 로그), 복귀 판정 시 `/cn:set` 덮어쓰기 해제. `<task-notification>`·`<cross-session-message`·`<teammate-message` 는 turn 시작만 기록하고 활동으로 안 셈. `wake_off` 는 안 건드림 |
| SessionStart 훅 (`clear\|compact`) | `scripts/on_session_start.py` | `suppressed_at_ns` 기록 — 그 뒤 진짜 입력이나 Stop 이 올 때까지 깨우기 억제 |
| SessionEnd 훅 (async) | `scripts/on_session_end.py` | 이 세션 marker 삭제 + 7일 넘은 marker 정리 |
| UserPromptExpansion 훅 | `scripts/on_status_command.py` | `/cn:status`·`/cn:set`·`/cn:config` 를 LLM turn 없이 처리 (`cn_status.py`·`cn_set.py`·`cn_config.py`) |
| 깨우기 판정 | `scripts/refresh.py --now` | mod 가 실행 (sleep 없음). 재확인(활성 설치본·세션 종료·진행 중 turn·억제) → `remaining_wakes` 0 이면 건너뜀 → `wake_count` 증가·덮어쓰기 차감을 marker 에 저장(실패 시 깨우지 않음) → stderr 에 ping 쓰고 exit 2 |
| 판정 공용 규칙 | `lib/wake_plan.py` | `remaining_wakes`(꺼짐 0 / 덮어쓰기 중 충전 남은 것 / 아니면 `auto_wakes - wake_count`), `survive_until_ns`(기준 + 남은 횟수 × interval + ttl). `refresh.py`·`cn_set.py`·`cn_status.py` 공유, mod 띠도 같은 식 |

## 깨우기 흐름

```
turn.step (메인 대화, 캐시 read+creation > 0)
  └─ base = 그 요청의 시작 시각           ← mod atom
1초 tick
  ├─ 띠·토스트 갱신 (base + cache_ttl_minutes 까지 남은 시간)
  └─ refresh_interval ≤ now - base < cache_ttl 이고 이 base 로 아직 안 깨웠으면
       └─ refresh.py --now  (stdin: session_id, 상한 1분)
            ├─ exit 0 → 끝 (건너뜀 — 사유는 cn.log 의 [refresh] 줄)
            └─ exit 2 → stderr 의 [cn:keepalive 줄만 prompt.submit
                          └─ ping turn 이 캐시를 읽음 → turn.step 이 base 갱신 → 다음 주기 (연쇄)
  └─ 이 base 로 이미 깨웠어도, 깨우기 구간 안에서 marker 의 충전 시각(set_charged_at_ns)이 바뀌었고
     남은 충전이 있으면(꺼짐 아님) refresh.py --now 를 1회 더 실행  ← /cn:set 재판정
```

- 연쇄 상한: 자리비움마다 `auto_wakes`, `/cn:set N` 덮어쓰기 중이면 N. `/cn:set 0|off`(`wake_off`)는 세션 끝까지 0.
- 마지막 Stop 뒤 turn 시작이 있으면 Python 이 건너뛴다: `max(last_user_activity_at_ns, last_turn_start_at_ns) > latest_fire` — 진짜 입력뿐 아니라 팀메이트·다른 세션 메시지·`<task-notification>` 으로 시작해 아직 Stop 이 없는 turn(권한·질문 대기 포함)에도 ping 을 끼우지 않는다.
- 억제는 `suppressed_at_ns > max(last_user_activity_at_ns, latest_fire)` 일 때만 — 압축 뒤 Stop 까지 간 새 캐시는 깨운다.

## 상태 저장소

| 저장소 | 쓰는 쪽 | 내용 |
|---|---|---|
| mod atom (세션 메모리) | mod 만 | `base`, 띠 `label`, `config`, 토스트·깨우기 1회 가드(`warnedFor`·`expiredFor`·`wokeFor`), 깨울 때 본 충전 시각 `wokeCharge`, 읽어 둔 `marker` |
| `~/.cache-necromancer/marker/<sid>.json` | **Python 만** | `latest_fire`, `wake_count`, `last_wake_at`·`last_wake_at_ns`, `last_user_activity_at_ns`, `last_turn_start_at_ns`, `suppressed_at_ns`, `set_budget_remaining`·`set_budget_total`·`set_charged_at_ns`, `wake_off`, `last_prompt`·`cwd` |
| `~/.cache-necromancer/config.toml` | 사용자·터미널 설정 메뉴(`scripts/cn_config.py`)·Python(템플릿 생성) | 설정 5개 키. 옛 키는 무시, 메뉴 저장 때 삭제 |
| `~/.cache-necromancer/cn.log.YYYY-MM-DD` | Python (`lib/logger.py`) | `[refresh]`·`[return]` 등 판정 로그. 자동 삭제 없음 |

mod 는 marker 를 기준 시각이 있는 동안 5초 간격·깨우기 직후에 **읽기만** 한다 (띠 표시와 무관 — 재판정에 필요). 경로 루트는 모두 `$CN_ROOT` 가 있으면 그것.

## 설정 반영 시점

- mod: 세션 시작(`session.start`) 때, 또는 리로드 뒤 첫 tick 에 읽는다 → 띠·깨우기 시점(`cache_ttl_minutes`·`refresh_interval_minutes`·`countdown`·`language`, 뒤 정보용 `auto_wakes`)은 새 세션 또는 `/reload-plugins` 뒤부터. 매 tick 재읽기는 v0.13.0 예정.
- Python: 실행마다 읽는다 → 깨우기 횟수(`auto_wakes`)·`/cn:*` 문구는 다음 판정부터.

## 알려진 제약

- mods 는 Claude Code v2.1.286 이상. 그 미만은 `modules` 를 무시해 띠·깨우기가 없고 Python 훅·`/cn:*` 만 동작한다.
- `/reload-plugins` 뒤 `session.start` 가 안 올 수 있다 — 0.11.0 부터 `ui.render`·`turn.step` 중 먼저 오는 쪽에서 타이머를 건다. settings 훅(`hooks.json`)의 경로는 여전히 재시작해야 바뀐다 ([CLAUDE.md](../CLAUDE.md)).
- Esc 로 중단한 turn 은 Stop 이 없어 다음 완료 turn 까지 깨우지 않는다.
- Claude Code 재시작은 SessionEnd 로 marker 를 지워 `/cn:set` 덮어쓰기·`wake_off` 가 사라진다 (resume 후 다시 설정).
- 설정 파일 문법 오류 때 Python 은 전체 기본값, mod 는 읽히는 줄의 값을 쓴다 — 해석 통일은 v0.13.0 예정.

실측 기록: 2026-10-07 깨우기 1회 cache_read 355,998 / creation 271

# cache-necromancer v0.3.0 — TECH_SPEC

> **Status**: Draft (작성 2026-05-16)
> **Author**: Brody Byun
> **Related**: [PRD](2026-05-15-cache-necromancer-v0.3.0-PRD.md), [PLAN](../plans/2026-05-15-cache-necromancer-v0.3.0-PLAN.md)
> **Supersedes**: v0.2.x daemon-based subprocess fire architecture

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code chat session (PID A)                            │
│                                                              │
│  user input → assistant turn → Stop event                    │
│       ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Plugin manifest 가 등록한 hook (asyncRewake: true)    │   │
│  │ command: python3 ${CLAUDE_PLUGIN_ROOT}/scripts/      │   │
│  │          refresh.py                                  │   │
│  └──────────────────────────────────────────────────────┘   │
│       ▼ background fork                                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ refresh.py (PID B):                                  │   │
│  │  1. config 로드 (~/.cache-necromancer/config.toml)   │   │
│  │  2. marker 갱신 (latest_fire = now, my_ts = now)     │   │
│  │  3. count 체크 (≥ max_refresh_count → exit 0)        │   │
│  │  4. mode 별 분기:                                     │   │
│  │     - notify: sleep → osascript → exit 0              │   │
│  │     - auto:   sleep → my_ts==latest_fire 확인 → exit 2│   │
│  │     - hybrid: sleep → osascript → wait → 확인 → exit 2│   │
│  │  5. exit 2 시 stderr 에 ping 메시지                   │   │
│  └──────────────────────────────────────────────────────┘   │
│       ▼ (exit 2 시 Claude Code 가 wake)                      │
│  새 user-role message (= stderr) → assistant 응답 'ok'        │
│  → 다시 Stop event → loop                                    │
└─────────────────────────────────────────────────────────────┘
```

핵심 원리: **chat 프로세스 (PID A) 자체가 wake**. system prompt + tools 가 byte-exact 보존되어 cache prefix 100% hit.

## 2. 핵심 컴포넌트

| 파일 | 역할 |
|---|---|
| `.claude-plugin/plugin.json` | 플러그인 메타. version 0.3.0 으로 bump. `userConfig.mode` 유지 |
| `hooks/hooks.json` | Stop hook (asyncRewake: true) + UserPromptSubmit (marker reset) + SessionEnd (marker cleanup) + UserPromptExpansion (status) |
| `scripts/refresh.py` | (신규) keep-alive 본체. config + marker + sleep + mode 분기 + exit 2 |
| `scripts/on_user_prompt.py` | (수정) user input 시 marker count reset |
| `scripts/on_session_end.py` | (수정) 세션 종료 시 marker file 삭제 |
| `scripts/on_status_command.py` | (유지) `/cn:status` slash command wrapper. `cn_status.py` 호출 |
| `scripts/cn_status.py` | (재작성) v0.3.0 status 출력 |
| `lib/config.py` | (수정) v0.3.0 옵션만 남기고 폐기 옵션 detect 시 deprecated 경고. **`refresh_interval_minutes` default 55 → 50 으로 변경** |
| `lib/marker.py` | (신규) marker file 읽기/쓰기 단일 책임. **atomic write 사용 (`tempfile + os.replace()`)** |
| `lib/logger.py` | (유지) refresh.py / on_user_prompt.py / cn_status.py 모두 사용 |
| `lib/session_id.py` | (유지) sid_hash sanitize. v0.3.0 marker file 명에도 사용 |
| `lib/mask.py` | (유지) cn:status 의 sid 마스킹 표시 |
| `pyproject.toml` | (수정) version 0.2.0 → 0.3.0, packages include 에서 `daemon*` 제거, `[project.scripts] cn = "lib.install:main"` 추가 |
| `lib/install.py` | (신규) `cn install` / `cn uninstall` CLI (plugin 미사용 fallback) |
| `lib/notify.py` | (신규) macOS osascript 알림 wrapper |
| `commands/cn:status.md` | (유지) slash command 정의 |
| `commands/cn:config.md` | (유지) 모드 비교 정의 |

## 3. Data structures

### 3.1 marker file: `~/.cache-necromancer/marker/<sid_hash>.json`

```json
{
  "latest_fire": 1715856000,
  "wake_count": 3,
  "last_wake_at": 1715852400,
  "session_started_at": 1715840000
}
```

- `latest_fire` (Unix timestamp): 가장 최근 Stop hook fire 시각. refresh.py 가 매 fire 마다 자기 my_ts 와 비교해 같으면 wake, 다르면 skip
- `wake_count` (int): 누적 wake **또는 notify 횟수** (mode 무관 — auto/hybrid wake 시 ++ / notify 알림 발송 시 ++). `max_refresh_count` 초과 시 skip. user input 시 0 reset
- `last_wake_at`: 직전 wake (또는 notify) 시각. cn:status 표시용
- `session_started_at`: 세션 시작 시각. cn:status 표시용

sid_hash 는 v0.2.x 의 `lib/session_id.py` 의 `sanitize()` 그대로 사용 (CLAUDE_CODE_SESSION_ID 의 SHA256 단축).

**Atomic write**: `Marker.save()` 는 `tempfile.NamedTemporaryFile(dir=marker_dir)` 로 임시 파일 작성 후 `os.replace()` 로 원자적 이동. POSIX 보장. 동시 read/write 시 partial JSON 안 보임.

**저장 실패 처리 (graceful degradation)**: `Marker.save()` 가 권한 거부 / 디스크 풀 (ENOSPC) / tempfile 생성 실패 등으로 예외 발생 시 호출자 (refresh.py / on_user_prompt.py) 가 catch 해서 `logger` 로 기록 후 `exit 0`. 이전 marker 파일은 그대로 보존 (replace 가 일어나지 않았으므로). 결과: wake 1회 포기 (cache rebuild 비용 1회 발생 가능), chat 동작 자체는 영향 X. cache wake 는 best-effort 기능이라 실패 시 chat 차단 X 가 원칙.

### 3.2 config: `~/.cache-necromancer/config.toml`

```toml
[general]
mode = "hybrid"                       # notify | auto | hybrid
refresh_interval_minutes = 50         # cache TTL 만료 직전
max_refresh_count = 10                # 한 세션 최대 wake 횟수

[notify]
system_notification = true            # macOS osascript

[refresh]
hybrid_wait_seconds = 60              # hybrid 모드 알림 후 사용자 input 대기
```

폐기 옵션 (`terminal_bell`, `imminent_threshold_minutes`, `fire_timeout_seconds`, `[advanced]` 전체) 이 파일에 있으면 `lib/config.py` 가 로드 시 stderr 로 deprecated 경고 (load 자체는 성공).

## 4. refresh.py 동작 sequence

### 4.1 공통 진입

```python
sid_hash = sanitize(os.environ["CLAUDE_CODE_SESSION_ID"])
marker = Marker.load(sid_hash)        # 없으면 새로 생성
my_ts = int(time.time())
marker.latest_fire = my_ts
marker.save()

if marker.wake_count >= config.max_refresh_count:
    log_skip(reason="max_refresh_count_reached")
    sys.exit(0)
```

### 4.2 mode = notify

```python
sleep(config.refresh_interval_minutes * 60)

# timestamp 비교 — 더 최근 fire 가 있으면 skip (auto/hybrid 와 동일)
marker = Marker.load(sid_hash)
if marker.latest_fire > my_ts:
    sys.exit(0)

marker.wake_count += 1   # 알림 발송도 max_refresh_count 에 포함
marker.last_wake_at = int(time.time())
marker.save()

notify("cache-necromancer: cache 만료 임박, 직접 chat 으로 돌아오세요")
sys.exit(0)   # wake 안 함
```

cache 갱신 효과 0. 사용자가 직접 돌아와서 input 해야 함. wake_count 는 알림 횟수도 포함하여 자리비움 시 무한 알림 차단.

### 4.3 mode = auto

```python
sleep(config.refresh_interval_minutes * 60)

# timestamp 비교 — 더 최근 fire 가 있으면 skip
marker = Marker.load(sid_hash)
if marker.latest_fire > my_ts:
    log_skip(reason="superseded_by_newer_fire")
    sys.exit(0)

marker.wake_count += 1
marker.last_wake_at = int(time.time())
marker.save()

print("[cn:keepalive] reply 'ok' only. No tools, no analysis.", file=sys.stderr)
sys.exit(2)
```

### 4.4 mode = hybrid

```python
sleep(config.refresh_interval_minutes * 60)

marker = Marker.load(sid_hash)
if marker.latest_fire > my_ts:
    sys.exit(0)

notify("cache-necromancer: 60초 후 자동 wake. 직접 input 시 취소")
sleep(config.hybrid_wait_seconds)

# 60초 사이 사용자가 input 했는지 재확인
marker = Marker.load(sid_hash)
if marker.latest_fire > my_ts:
    log_skip(reason="user_input_during_hybrid_wait")
    sys.exit(0)

marker.wake_count += 1
marker.last_wake_at = int(time.time())
marker.save()

print("[cn:keepalive] reply 'ok' only. No tools, no analysis.", file=sys.stderr)
sys.exit(2)
```

## 5. on_user_prompt.py (marker reset)

사용자가 chat 에 input 시 fire 되는 hook. v0.2.x 의 state 추적 로직 폐기. v0.3.0 동작:

```python
sid_hash = sanitize(os.environ["CLAUDE_CODE_SESSION_ID"])
marker = Marker.load(sid_hash)
marker.wake_count = 0   # user 가 active 하므로 자리비움 상한 reset
marker.save()
```

→ user input 마다 wake_count = 0 reset. `max_refresh_count` 는 "한 번 자리비움" 의 상한 의미.

**max_refresh_count 도달 후 user input flow**:
1. 자리비움 → wake_count = 10 도달 → 모든 추가 refresh.py 가 진입부에서 exit 0 (wake/notify 안 함)
2. 사용자가 돌아와 input → on_user_prompt.py 가 wake_count = 0 reset
3. user input 자체가 새 user turn → assistant 응답 → **새 Stop hook fire** → 새 refresh.py 진입 → wake_count = 0 이므로 정상 sleep + wake 사이클 재개
4. 사용자 input 직후 wake 까지 50분 대기는 정상 (cache 가 막 fresh 한 상태이므로 굳이 즉시 wake 불필요)

## 6. on_session_end.py (cleanup)

```python
sid_hash = sanitize(os.environ["CLAUDE_CODE_SESSION_ID"])
marker_dir = Path.home() / ".cache-necromancer/marker"
(marker_dir / f"{sid_hash}.json").unlink(missing_ok=True)

# 동일 시점에 marker_dir 전체 glob → 7일 초과 stale 파일 정리
# (다른 세션이 SessionEnd 못 받고 죽었을 경우 누적 방지)
cutoff = time.time() - 7 * 86400
for stale in marker_dir.glob("*.json"):
    try:
        if stale.stat().st_mtime < cutoff:
            stale.unlink(missing_ok=True)
    except OSError:
        pass
```

트리거: **현재 세션의 SessionEnd 마다** marker_dir 전체 glob. claude 가 한 번도 정상 종료하지 않으면 stale 누적되지만, 일반 사용 패턴에서 거의 발생 안 함.

## 7. lib/install.py — `cn install` / `cn uninstall`

plugin manifest 로 자동 등록되는 환경에서는 불필요. 단 다음 케이스 fallback:
- 사용자가 plugin marketplace 안 쓰고 git clone 으로 설치
- 사용자가 settings.local.json 에 직접 hook 추가하고 싶음

### 7.1 `cn install` 동작

```bash
$ cn install
# 1. v0.2.x stale daemon 아티팩트 detect (PRD §6.1 마이그레이션):
#    - ~/.cache-necromancer/lock 파일 존재 → "v0.2.x daemon 정지 필요: pkill -f 'python.*-m daemon'" 안내
#    - ~/.cache-necromancer/state/ 디렉토리 비어있지 않음 → "v0.2.x state 정리 필요: rm -rf ~/.cache-necromancer/state" 안내
#    - 자동 삭제 X — 사용자가 직접 명령 실행. detect 후 stdout 으로 출력만
# 2. ~/.claude/settings.json 또는 settings.local.json detect
# 3. 기존 Stop hook 항목 검색
#    - cache-necromancer hook 이 이미 있으면: "이미 설치됨" 출력 후 exit 0
#    - 다른 사용자 hook 이 있으면: "기존 hook 과 공존 — 충돌 가능. 계속? [y/N]"
#    - 없으면: 새 hook 추가
# 4. settings.json 에 다음 추가 (timeout 필드 의도적 생략 — 아래 주석 참조):
#    {
#      "hooks": {
#        "Stop": [{"hooks": [{
#          "type": "command",
#          "command": "python3 /path/to/cache-necromancer/scripts/refresh.py",
#          "asyncRewake": true
#        }]}]
#      }
#    }
# 5. stdout 안내:
#    - settings hot-reload 안 되므로 새 chat 세션 필요
#    - claude -c resume 시 첫 wake 가 cache rebuild 비용 가능
#    - deprecated config 옵션 detect 되면 경고
```

**timeout 필드 미지정 이유**: hook timeout 의 default 는 60s 인데, refresh.py 는 sleep 50분 = 3000s. POC C 검증 결과 `asyncRewake: true` (+ implied `async: true`) 의 background process 는 **hook timeout 적용을 받지 않음** (POC C 에서 timeout 60s + sleep 30분 setting 이 정상 wake). 단 향후 Claude Code 변경 가능성 있으니 §11.2 수동 검증 항목에 "asyncRewake background 의 timeout 동작" 명시. plugin manifest 의 `hooks/hooks.json` 에서도 동일하게 timeout 필드 생략.

### 7.2 `cn uninstall` 동작

settings.json 에서 cache-necromancer 관련 hook 만 제거. 다른 hook 보존. config.toml 과 marker file 은 그대로 (사용자가 수동으로 `rm -rf ~/.cache-necromancer` 가능).

### 7.3 entry point

기존 `pyproject.toml` 수정 (신규 생성 아님 — v0.2.x 부터 존재):
```toml
[project]
name = "cache-necromancer"
version = "0.3.0"               # 0.2.0 → 0.3.0 bump

[project.scripts]
cn = "lib.install:main"         # 신규 추가

[tool.setuptools.packages.find]
include = ["lib*", "scripts*"]  # 기존 ["lib*", "daemon*", "scripts*"] 에서 daemon* 제거
```

## 8. cn:status 출력

```
🔮 cache-necromancer 상태

mode: hybrid · refresh_interval: 50m · max_refresh: 10

┌─ 세션 (현재) ────────────────────────────────────┐
│ sid:               a1b2c3...****                 │
│ 시작:               2026-05-16 09:00:00          │
│ wake/notify count: 3 / 10                        │
│ 마지막 wake/notify: 2026-05-16 11:30:00 (45m 전) │
│ 다음 발동 예상:     2026-05-16 12:20:00 (5m 후)  │
│ cache 추정:        2026-05-16 12:30:00 만료      │
└──────────────────────────────────────────────────┘

┌─ 다른 세션 ──────────────────────────────────────┐
│ d4e5f6...****  · wake/notify 1/10 · 마지막 5h 전 │
└──────────────────────────────────────────────────┘

레이블 표기 사유: `wake_count` 가 mode 무관 통합 카운터 (§3.1) 라 `notify` mode 사용자가 "wake 됐다" 로 오해하지 않도록 `wake/notify` 로 명시. mode = `auto` 인 세션도 동일 레이블 (mode 별 분기 X — 단순 일관성 우선).

┌─ 설정 상태 ──────────────────────────────────────┐
│ plugin: cache-necromancer v0.3.0 (active)        │
│ hook 등록: ✅ (plugin manifest)                  │
│ deprecated config: 없음                          │
└──────────────────────────────────────────────────┘
```

특이 case:
- hook 미등록 (plugin install 후 새 세션 X): "⚠️ settings hot-reload 안 됨. 새 chat 세션 필요" 표시
- mode = notify: "cache 갱신 효과 없음 (알림 only)" 명시
- deprecated config 옵션 있음: 경고 + 어떤 옵션인지 list

## 9. Race / edge case 처리

| 케이스 | 처리 |
|---|---|
| 매 user turn 마다 hook fire (multiple sleep 누적) | 모든 fire 가 동시 sleep 진행. 마지막 fire 만 latest_fire == my_ts 이라 wake. 나머지는 skip. **별도 lock 불필요** (단 marker write 자체는 atomic — 아래 항목) |
| 동시 marker.save() (concurrent write) | `tempfile + os.replace()` 로 atomic write. partial JSON 또는 corrupt 발생 안 함. read 시 항상 완성된 JSON 또는 직전 버전을 보게 됨 |
| asyncRewake background process 의 hook timeout 적용 여부 | POC C 검증으로 timeout 미적용 사실상 확정. settings.json/hooks.json 에서 timeout 필드 생략. §11.2 수동 검증에 동작 변화 감시 항목 포함 |
| Wake 직후 바로 또 Stop hook fire | wake_count 1 증가. 또 sleep 50분. user input 없으면 다음 wake. user input 있으면 marker reset. 무한 wake 는 max_refresh_count 로 차단 |
| 사용자가 `claude -c` 로 resume 중 marker file 살아있음 | latest_fire 가 옛날 값. 새 hook fire 가 latest_fire 갱신 → 정상 동작 |
| sid_hash 충돌 (불가능에 가까움) | SHA256 truncated 사용. 이론적 충돌 가능성 무시 가능 |
| marker dir 권한 문제 | refresh.py 가 mkdir 시도 실패 → log + exit 0 (wake 포기, chat 영향 X) |
| config.toml syntax error | load 실패 → stderr 경고 + 기본값 사용 (refresh 자체는 동작) |
| Claude Code 종료 (SIGKILL) 시 background sleep 살아있음 | sleep 종료 후 stderr 출력 시도하나 부모 프로세스 없음 → 자동 종료. cleanup 불필요 |

## 10. 폐기 대상 정확한 list

### 폐기 — 디렉토리/파일
- `daemon/` 전체 (10개 .py file: __main__, clock, handler, notifier, poller, refresh, scheduler, spawn, transcript, watchdog)
- `lib/lockfile.py` (daemon lock 전용)
- `lib/state.py` (daemon state 전용 — marker.py 로 대체)
- `lib/plugin_state.py` (state file 관리)
- `lib/box_renderer.py` 일부 (status 출력 단순화 후 재검토)
- `scripts/on_stop.py` → **`scripts/refresh.py` 로 replace** (rename 아님 — daemon spawn 로직 폐기, asyncRewake sleep 로직 신규)
- `tests/test_*.py` 의 daemon 관련 (PR #11 의 16개 회귀 가드 + daemon spawn 테스트)
- `~/.cache-necromancer/lock` (daemon lock file)
- `~/.cache-necromancer/state/` (per-session state JSON 파일들)
- `~/.cache-necromancer/fire.log.*` (subprocess fire log)

### 유지 — v0.3.0 에서도 사용
- `lib/logger.py` — refresh.py 의 skip/wake 로그, cn_status.py 의 출력 로그
- `lib/session_id.py` — sid_hash sanitize (marker file 명)
- `lib/mask.py` — cn:status 의 sid 마스킹 (`a1b2c3...****`)
- `lib/mode_help.py` — `/cn:config` 의 모드 비교 표
- `lib/__init__.py` — 패키지 표식
- `commands/cn:status.md`, `commands/cn:config.md` — slash command 정의
- `scripts/on_session_end.py` — 로직 변경 (marker cleanup) 하나 파일은 유지
- `scripts/on_user_prompt.py` — 로직 변경 (wake_count reset) 하나 파일은 유지
- `scripts/on_status_command.py` — `/cn:status` slash backend wrapper 유지

### Config 옵션 (lib/config.py)
- `RefreshConfig.prompt`, `RefreshConfig.fire_timeout_seconds` (refresh.hybrid_wait_seconds 만 유지)
- `NotifyConfig.terminal_bell`, `NotifyConfig.imminent_threshold_minutes` (system_notification 만 유지)
- `AdvancedConfig` 전체 (12개 옵션)

### 명령
- `/cn:dry-run` (subprocess fire preview — 의미 사라짐)
- `commands/cn:dry-run.md` (있다면)

### 환경변수
- `CLAUDE_PLUGIN_OPTION_MODE` 는 유지 (userConfig 통한 mode 주입)

## 11. 테스트 전략

### 11.1 자동 테스트 (pytest)

| 대상 | 테스트 케이스 (assertion) |
|---|---|
| `lib/config.py` | 호환 옵션 로드 → 5개 옵션 값 일치 / deprecated 옵션 → stderr 경고 capture / syntax error → 기본값 fallback + 경고 |
| `lib/marker.py` | load/save → 저장 후 load 한 값 일치 / **concurrent writer N개 + reader N개 동시 (threading) → 모든 read 가 valid JSON (이전 또는 신규 complete marker) 임을 assert / load 실패 0건** / 권한 에러 → exception raise (호출자가 catch + log + exit 0) / save 중 ENOSPC 시뮬레이션 → 이전 marker 보존 + exception |
| `scripts/refresh.py` (sleep monkey patch) | mode=auto → exit 2 + wake_count++ + last_wake_at 갱신 / mode=notify → exit 0 + wake_count++ (notify 도 carbon) + last_wake_at 갱신 / mode=hybrid → 60s wait 후 marker 재load → input 있으면 exit 0 / max_refresh_count 도달 → 진입부 exit 0 + wake_count 변경 없음 / latest_fire > my_ts → exit 0 + wake_count 변경 없음 |
| `scripts/on_user_prompt.py` | wake_count = 0 reset → 다른 필드 (latest_fire, last_wake_at) 보존 |
| `scripts/on_session_end.py` | 현재 sid marker 삭제 / 7일 초과 stale 삭제 / 7일 미만 stale 보존 |
| `lib/install.py` | settings.json 신규 추가 → JSON valid + Stop hook 1개 / 기존 cn hook → "이미 설치됨" + 변경 0 / 다른 hook 존재 → 경고 prompt |
| `scripts/cn_status.py` | mode/wake_count/last_wake_at/cache 만료 추정 출력 포함 / deprecated config → 경고 표시 / hook 미등록 → "새 세션 필요" 표시 |

목표 커버리지: ≥ 80% (v0.2.x 의 daemon 부분 폐기 후 base 작아져 비율 자연 상승).

### 11.2 수동 검증 (사용자 테스트)

asyncRewake 자체는 자동 테스트 불가능 (Claude Code runtime 필요). 다음을 수동 확인:
1. `/plugin install cache-necromancer` 후 새 세션
2. user input → 50분 (또는 단축 5분) 대기 → wake 발생 확인
3. cache_read_input_tokens ≈ turn 1 의 cache_creation_input_tokens (100% hit 검증)
4. mode 별 동작 (notify 알림만, hybrid 60초 대기 후 wake, auto 즉시 wake)
5. user input 시 wake_count reset 확인
6. max_refresh_count 도달 시 wake 차단 확인

수동 테스트는 시간 소요 큼 — 검증용으로 `refresh_interval_minutes = 1` (config override) + `hybrid_wait_seconds = 5` 로 단축 가능.

## 12. References

- [PRD](2026-05-15-cache-necromancer-v0.3.0-PRD.md)
- [PLAN](../plans/2026-05-15-cache-necromancer-v0.3.0-PLAN.md)
- [POC C — long-sleep cache survival](../../handoff/2026-05-15-v0.3.0-asyncrewake-fix.md)
- [Claude Code hooks docs (asyncRewake field)](https://code.claude.com/docs/en/hooks.md)
- [Claude Code plugin manifest docs](https://code.claude.com/docs/en/plugins.md)
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

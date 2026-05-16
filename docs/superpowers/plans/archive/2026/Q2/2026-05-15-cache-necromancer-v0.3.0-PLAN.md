# cache-necromancer v0.3.0 — PLAN

> **Status**: Draft (작성 2026-05-16)
> **Author**: Brody Byun
> **Related**: [PRD](../specs/2026-05-15-cache-necromancer-v0.3.0-PRD.md), [TECH_SPEC](../specs/2026-05-15-cache-necromancer-v0.3.0-TECH_SPEC.md)
> **PR strategy**: 단일 PR (docs + 구현 + README), 10 commits, 사용자 결정 (300줄 룰 deviate)

## 1. 한 줄 요약

v0.2.x daemon-based architecture 를 v0.3.0 asyncRewake hook architecture 로 전환. 단일 PR 안에서 10개 commit 으로 분해하여 작업 흐름 순서대로 진행.

## 2. PR 정보

| 항목 | 값 |
|---|---|
| Branch | `feature/v0.3.0-asyncrewake-architecture` (이미 생성, commit 0개) |
| Target | `main` |
| PR 구조 | 단일 PR (docs + 구현 + README + plugin manifest 모두) |
| PR 코드 라인 | 300줄 룰 deviate (사용자 결정 — daemon 폐기로 -1500줄 / 신규 +500줄 예상, net 감소) |
| Commit 수 | 10개 (작업 흐름 순서) |
| Reviewer | 사용자 + codex (각 commit 후 또는 일괄) |

## 3. Commit 분해 (10개)

각 commit 은 독립적으로 빌드/테스트 통과해야 함 (bisect 가능 보장).

### Commit 1 — `docs(v0.3.0): PRD + TECH_SPEC + handoff 문서 추가`

**파일**:
- `docs/superpowers/specs/active/2026-05-15-cache-necromancer-v0.3.0-PRD.md`
- `docs/superpowers/specs/active/2026-05-15-cache-necromancer-v0.3.0-TECH_SPEC.md`
- `docs/superpowers/plans/archive/2026/Q2/2026-05-15-cache-necromancer-v0.3.0-PLAN.md` (이 파일)
- `docs/handoff/archive/2026/Q2/2026-05-15-v0.2.2-cache-investigation.md`
- `docs/handoff/archive/2026/Q2/2026-05-15-v0.3.0-asyncrewake-fix.md`

**작업**:
- 새 파일 5개 추가 (이미 작성 완료)
- `docs/handoff/archive/2026/Q2/2026-05-15-v0.2.2-fire-tty-rootcause.md` 는 superseded 라 commit 제외 (별도 결정 — 삭제 또는 보관)

**검증**:
- `git add` + `git commit` (테스트 무관)

---

### Commit 2 — `chore(daemon): daemon/ 디렉토리 + lock/state lib 폐기`

**파일** (삭제):
- `daemon/` 전체 (`__init__.py`, `__main__.py`, `clock.py`, `handler.py`, `notifier.py`, `poller.py`, `refresh.py`, `scheduler.py`, `spawn.py`, `transcript.py`, `watchdog.py`)
- `lib/lockfile.py`
- `lib/state.py`
- `lib/plugin_state.py`
- `tests/` 의 daemon 관련 테스트 (PR #11 의 16개 회귀 가드 + daemon spawn 테스트)
- `pyproject.toml` 의 `daemon*` 패키지 include 제거

**작업**:
- 삭제 후 `pytest` 실행 → daemon import 에러 발생하는 다른 코드 임시 처리 (다음 commit 에서 정리)
- 또는 daemon import 하는 코드 (예: `cn_status.py` 의 `is_daemon_alive`) 임시 stub 처리

**검증**:
- `pytest` → daemon 관련 테스트 전부 사라짐 확인
- Python import 에러 0건 (있다면 다음 commit 에서 처리하기 위해 임시 stub)

---

### Commit 3 — `feat(lib): marker.py 신규 + atomic write + concurrent 테스트`

**파일** (신규):
- `lib/marker.py` — `Marker` 클래스 (load/save/atomic write/저장 실패 graceful)
- `tests/test_marker.py` — load/save 일치, concurrent writer+reader (threading), ENOSPC 시뮬레이션, 권한 에러

**작업**:
- TECH_SPEC §3.1 + §11.1 marker.py 행 그대로 구현
- `tempfile.NamedTemporaryFile(dir=marker_dir)` + `os.replace()` atomic 패턴
- 저장 실패 시 raise (호출자가 catch)
- 7일 stale 정리 helper (on_session_end 가 사용)

**검증**:
- `pytest tests/test_marker.py` → 100% 통과
- threading concurrent 테스트가 atomic 보장 검증

---

### Commit 4 — `feat(lib): config.py v0.3.0 옵션 정리 + deprecated detect`

**파일** (수정/삭제):
- `lib/config.py` 수정:
  - `RefreshConfig`: `prompt`, `fire_timeout_seconds` 폐기 → `hybrid_wait_seconds` 만 유지
  - `NotifyConfig`: `terminal_bell`, `imminent_threshold_minutes` 폐기 → `system_notification` 만 유지
  - `AdvancedConfig` 전체 폐기
  - `Config.refresh_interval_minutes` default 55 → 50
  - `load_config()` 가 deprecated 옵션 detect 시 stderr 경고
  - `_DEFAULT_TEMPLATE` v0.3.0 형식으로 재작성
- `tests/test_config.py` (기존 수정 또는 신규):
  - 호환 옵션 5개 로드 → 값 일치
  - deprecated 옵션 → stderr 경고 capture
  - syntax error → 기본값 fallback

**검증**:
- `pytest tests/test_config.py` → 통과
- 기존 v0.2.x config.toml 로드 시 경고 + 기본값 동작 확인

---

### Commit 5 — `feat(scripts): refresh.py 신규 + mode 분기 + sleep monkey patch 테스트`

**파일** (신규/replace):
- `scripts/refresh.py` 신규 (TECH_SPEC §4 의사코드)
- `scripts/on_stop.py` **삭제** (refresh.py 로 replace)
- `tests/test_refresh.py` 신규:
  - mode=auto → exit 2 + wake_count++ + last_wake_at 갱신
  - mode=notify → exit 0 + wake_count++ + last_wake_at 갱신
  - mode=hybrid → 60s wait 후 marker 재load → input 있으면 exit 0
  - max_refresh_count 도달 → 진입부 exit 0 + wake_count 변경 없음
  - latest_fire > my_ts → exit 0 + wake_count 변경 없음
  - sleep 은 monkey patch (`unittest.mock.patch('time.sleep')`)

**작업**:
- TECH_SPEC §4.1~§4.4 의사코드 그대로 구현
- stderr ping 메시지: `"[cn:keepalive] reply 'ok' only. No tools, no analysis."`
- Marker 권한/저장 실패 시 catch → log + exit 0

**검증**:
- `pytest tests/test_refresh.py` → 통과
- 모든 mode 의사코드 동작 일치

---

### Commit 6 — `refactor(scripts): on_user_prompt + on_session_end 단순화`

**파일** (수정):
- `scripts/on_user_prompt.py`:
  - 기존 v0.2.x state 추적 로직 폐기
  - TECH_SPEC §5: marker.wake_count = 0 reset 만
- `scripts/on_session_end.py`:
  - TECH_SPEC §6: 현재 sid marker 삭제 + 7일 stale glob 정리
- `tests/test_on_user_prompt.py`:
  - wake_count = 0 reset, 다른 필드 보존
- `tests/test_on_session_end.py`:
  - 현재 sid 삭제, 7일 초과 stale 삭제, 7일 미만 stale 보존

**검증**:
- `pytest tests/test_on_user_prompt.py tests/test_on_session_end.py` → 통과

---

### Commit 7 — `feat(plugin): hooks/hooks.json 재작성 + plugin.json v0.3.0 bump`

**파일** (수정):
- `hooks/hooks.json`:
  - Stop hook: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/refresh.py` + `asyncRewake: true` (timeout 필드 의도적 생략)
  - UserPromptSubmit: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/on_user_prompt.py`
  - SessionEnd: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/on_session_end.py`
  - UserPromptExpansion: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/on_status_command.py` (기존 유지)
- `.claude-plugin/plugin.json`:
  - version 0.2.0 → 0.3.0
  - description: "Auto-refresh Claude Code prompt cache TTL via Stop hook + asyncRewake"
  - userConfig.mode 유지

**검증**:
- JSON valid 확인 (`python3 -c "import json; json.load(open('hooks/hooks.json'))"`)
- plugin.json schema 일치

---

### Commit 8 — `feat(cli): lib/install.py 신규 + cn entry point + stale daemon detect`

**파일** (신규/수정):
- `lib/install.py` 신규:
  - `cn install`: stale daemon detect → settings.json hook 등록 (TECH_SPEC §7.1)
  - `cn uninstall`: settings.json 에서 cn hook 제거 (TECH_SPEC §7.2)
  - `cn` argparse entry: install/uninstall sub-command
- `pyproject.toml`:
  - `[project.scripts] cn = "lib.install:main"` 추가
  - version 0.2.0 → 0.3.0 bump
- `tests/test_install.py`:
  - settings.json 신규 추가 → JSON valid + Stop hook 1개
  - 기존 cn hook → "이미 설치됨" + 변경 0
  - 다른 hook 존재 → 경고 prompt
  - stale daemon detect → stdout 안내

**검증**:
- `pytest tests/test_install.py` → 통과
- `pip install -e .` 후 `cn --help` 동작 확인
- 임시 settings.json 으로 install/uninstall 사이클 테스트

---

### Commit 9 — `feat(status): cn_status.py v0.3.0 출력 재작성`

**파일** (재작성):
- `scripts/cn_status.py`:
  - daemon 박스 → 제거
  - 세션 (현재) 박스: sid + 시작 + wake/notify count + 마지막 wake/notify + 다음 발동 + cache 추정 (TECH_SPEC §8)
  - 다른 세션 박스: marker glob → 다른 sid 의 wake/notify count
  - 설정 상태 박스: plugin 등록 + hook 등록 + deprecated config 경고
  - mode 별 조건부 표시 (notify mode 는 "cache 갱신 효과 없음" 경고)
- `tests/test_cn_status.py`:
  - mode/wake_count/last_wake_at/cache 만료 추정 출력 포함
  - deprecated config → 경고 표시
  - hook 미등록 → "새 세션 필요" 표시

**검증**:
- `pytest tests/test_cn_status.py` → 통과
- 임시 marker + config 로 출력 시각 확인 (수동)

---

### Commit 10 — `docs(v0.3.0): README + CHANGELOG + Migration 가이드`

**파일** (수정):
- `README.md`:
  - 한 줄 설명 v0.3.0 으로 갱신 (asyncRewake 기반)
  - 설치: `/plugin install cache-necromancer` 한 명령 강조
  - mode 별 동작 표 (notify/auto/hybrid)
  - cn install CLI 사용법 (plugin 미사용 fallback)
  - 알려진 issue: settings hot-reload 안 됨, claude -c resume 시 첫 wake 비용
- `CHANGELOG.md`:
  - v0.3.0 entry: "asyncRewake architecture 전환. daemon 폐기, code -1500/+500"
  - Migration 안내 (PRD §6.1 그대로)
  - Breaking changes: deprecated config 옵션 list

**검증**:
- README 의 명령 line-by-line 검증 가능 (수동 follow)
- markdown lint 통과

---

## 4. 의존성 / 순서 제약

```
Commit 1 (docs) ─┬─→ 독립 (먼저 commit 가능)
                 │
Commit 2 (폐기) ──→ Commit 3, 4, 5, 6 (lib/scripts 수정) 의 전제
                 │
Commit 3 (marker) ─┬─→ Commit 5 (refresh.py) 의 전제
                   │
Commit 4 (config) ─┴─→ Commit 5 (refresh.py) 의 전제
                       │
Commit 5 (refresh) ────→ Commit 6 (on_user_prompt) 와 marker 공유
                       │
Commit 6 (on_*) ───────→ Commit 7 (hooks.json) 의 전제
                       │
Commit 7 (plugin) ─────→ 독립 (테스트 영향 X)
                       │
Commit 8 (cn install) ─→ Commit 9 (cn:status) 의 전제 (lib/install 의존성)
                       │
Commit 9 (status) ─────→ 독립
                       │
Commit 10 (docs) ──────→ 마지막
```

**병렬 가능**: Commit 7 (plugin manifest) 와 Commit 9 (status 출력) 는 다른 commit 와 독립적이라 순서 바꿔도 됨. 단 가독성 위해 작업 흐름 순서 유지.

## 5. 검증 절차

### 5.1 각 commit 후
```bash
pytest                          # 모든 테스트 통과
python3 -c "import lib; import scripts"  # import 에러 없음
```

### 5.2 PR push 직전 (전체 검증)
```bash
pytest --tb=short               # 전체 pass count 확인
pip install -e .                # cn 명령 등록 확인
cn --help                       # entry point 동작
python3 -c "import json; json.load(open('hooks/hooks.json'))"  # JSON valid
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"
```

### 5.3 사용자 실제 테스트 (PR push 후)
1. `/plugin uninstall cn-poc-D@cn-poc-D-marketplace` (POC 정리)
2. `/plugin marketplace remove cn-poc-D-marketplace`
3. 새 chat 세션 시작
4. `/plugin install cache-necromancer` (또는 git clone + cn install)
5. user input → 50분 sleep (검증용으로 `refresh_interval_minutes = 1` config override)
6. `/cn:status` → wake/notify count 표시 확인
7. cache_read_input_tokens ≈ turn 1 의 cache_creation_input_tokens (100% hit)
8. mode 별 동작 (notify 알림만, hybrid 60초 대기, auto 즉시 wake)

## 6. 임시 파일 정리 (작업 종료 시)

PR push 직전 또는 직후:
- `/tmp/cn-poc-A-silent/` 삭제
- `/tmp/cn-poc-B-midsleep/` 삭제
- `/tmp/cn-poc-C-longsleep/` 삭제
- `/tmp/cn-poc-D-plugin/` 삭제
- `/tmp/cn-test-refresh-bigctx.*` 삭제
- `/tmp/cn-asyncrewake-test/` 삭제
- `.claude/settings.local.json` (POC 임시 hook config) 삭제 또는 .gitignore 추가

## 7. PR description 템플릿

```markdown
## Summary
- v0.2.x daemon-based subprocess fire architecture → v0.3.0 asyncRewake hook architecture 전환
- fundamental fix: cache namespace 분리 문제를 chat 세션 self-wake 로 우회
- 코드 -1500줄 / +500줄 (net 감소)
- 5개 config 옵션 v0.2.x 호환 유지 (mode/refresh_interval/max_refresh/system_notification/hybrid_wait)

## 핵심 변경
- daemon/ + lock/state 폐기
- hooks/hooks.json + scripts/refresh.py 신규
- lib/marker.py + lib/install.py 신규
- cn install/uninstall CLI 신규

## Migration (v0.2.x → v0.3.0)
1. `pkill -f "python.*-m daemon" || true`
2. `rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state`
3. `/plugin update cache-necromancer` 또는 `/plugin install cache-necromancer`
4. 기존 chat 세션 재시작 (settings hot-reload X)

## 검증
- POC C: 30분 sleep 후 cache 100% hit (cr=44.55K, $0.044)
- 1M ctx: 두 번째 wake cc=586/cr=153.7K/$0.085 (94% 절감)
- pytest: N/N 통과 (PR 시점 채움)

## Test plan
- [ ] /plugin install cache-necromancer
- [ ] 새 chat 세션 + user input
- [ ] 50분 sleep 후 wake 발생 확인 (또는 refresh_interval_minutes=1 단축)
- [ ] mode 별 동작 (notify/auto/hybrid)
- [ ] cn:status 출력 정확성

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## 8. References

- [PRD](../specs/2026-05-15-cache-necromancer-v0.3.0-PRD.md)
- [TECH_SPEC](../specs/2026-05-15-cache-necromancer-v0.3.0-TECH_SPEC.md)
- [POC + 진단 doc](../../handoff/2026-05-15-v0.3.0-asyncrewake-fix.md)
- [v0.2.x 진단 evidence](../../handoff/2026-05-15-v0.2.2-cache-investigation.md)

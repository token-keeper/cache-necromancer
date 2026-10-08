# CLAUDE.md

이 파일은 Claude Code 가 이 repo 에서 작업할 때 따라야 할 프로젝트 규칙을 기록한다.

---

## 릴리즈 / marketplace 동기화 규칙

이 repo (`token-keeper/cache-necromancer`) 는 marketplace repo (`token-keeper/plugins`) 의 **git submodule** 로 포함되어 있다. submodule 은 특정 commit SHA 를 고정해서 가리키므로, 본체에 push 해도 marketplace 의 pointer 는 자동으로 따라오지 않는다.

따라서 **`main` 에 새 commit 이 올라가면 반드시 marketplace 의 submodule pointer 도 같이 갱신해야 한다.** 안 그러면 marketplace 를 통해 설치하는 사용자는 새 버전을 못 받는다.

### 작업 순서

0. 버전을 올린다 — 네 곳을 같은 값으로:
   - `.claude-plugin/plugin.json` 의 `version`
   - `hooks/hooks.json` 의 `description` 앞 `vX.Y.Z`
   - `CHANGELOG.md` 새 항목
   - `pyproject.toml` 의 `version`
1. 이 repo 의 `main` 에 commit + push (`origin/main`)
2. marketplace repo (`token-keeper/plugins`) clone 위치로 이동
3. submodule 갱신 + commit + push:
   ```bash
   cd plugins/cache-necromancer
   git fetch && git checkout main && git pull
   cd ../..
   git add plugins/cache-necromancer
   git commit -m "chore: bump cache-necromancer to vX.Y.Z"
   git push
   ```

### 참고

- marketplace clone 위치 (현재 사용자 환경): `~/.claude/plugins/marketplaces/token-keeper`
- 별도 dev clone 이 있다면 거기서 작업하는 게 안전 (Claude Code 가 marketplace 를 refresh 할 때 install cache 가 덮어씌워질 수 있음).

---

## 사용자 머신 반영 규칙 — "marketplace bump ≠ 활성 버전 갱신"

marketplace submodule pointer 를 bump 해도 **사용자 머신에서 실제로 실행되는 버전은 자동으로 바뀌지 않는다.** 이걸 혼동하면 "고친 코드가 적용 안 된 채 옛날 버그가 계속 보이는" 상황에 빠진다 (실제 발생: 0.4.0~0.4.2 를 만들었지만 사용자는 줄곧 0.3.13 로 실행 중이었음).

### 단계별로 무엇이 갱신되는가

| 동작 | 갱신되는 것 | 갱신 안 되는 것 |
|---|---|---|
| repo push + marketplace bump | GitHub / marketplace catalog | 사용자 install cache, 활성 버전 |
| `/reload-plugins` | install cache 에 새 버전 **다운로드만** | `installed_plugins.json` 활성 pointer, **이미 떠있는 세션의 hook 경로** |
| `/plugin update` | `installed_plugins.json` 활성 pointer (→ 새 버전) | 이미 떠있는 세션의 hook 경로 |
| **Claude Code 완전 재시작** | 새 세션이 활성 pointer 기준으로 hook register | — |

### 핵심 사실

- **활성 버전의 진짜 소스는 `~/.claude/plugins/installed_plugins.json`** 의 `installPath` / `version`. `/plugin` UI 가 보여주는 "Version: X" 는 marketplace catalog 의 최신 버전일 뿐, 활성 버전과 다를 수 있다.
- hook 의 `${CLAUDE_PLUGIN_ROOT}` 는 **세션 시작 시점에 활성 install 경로로 고정**된다. `/reload-plugins` 로는 이미 떠있는 세션의 경로가 안 바뀐다 → 재시작 필수.
- 따라서 새 버전을 사용자 머신에 실제 반영하려면 **`/plugin update` → Claude Code 재시작** 이 둘 다 필요하다.
- mod(`hooks/register.tsx`)는 다르다: v0.11.0 부터 `/reload-plugins` 로 다시 로드되면 첫 tick(`ui.render`·`turn.step`) 에 타이머를 걸고 설정을 읽는다. 다만 settings 훅(`hooks.json` 의 Python 훅) 경로는 위대로 재시작해야 바뀐다.

### 진단 시 확인 명령

```bash
# 활성 버전 (진짜 소스)
python3 -c "import json; d=json.load(open('$HOME/.claude/plugins/installed_plugins.json')); print([v for k,v in d['plugins'].items() if 'cache-necromancer' in k])"
# 깨우기 판정 기록 (오늘 로그)
grep '\[refresh\]' ~/.cache-necromancer/cn.log.$(date +%F)
```

v0.10.0 부터 깨우기는 mod 가 `refresh.py --now` 를 짧게 실행하는 방식이라 상주하는 refresh.py 프로세스가 없다 (예전 Stop 훅 asyncRewake 대기 프로세스는 사라졌다). 깨우기가 안 될 때는 활성 버전을 확인한 뒤 `~/.cache-necromancer/cn.log.*` 의 `[refresh]` 줄(wake·notify·skip 사유)로 판정 결과를 본다. 구조는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

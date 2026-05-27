# CLAUDE.md

이 파일은 Claude Code 가 이 repo 에서 작업할 때 따라야 할 프로젝트 규칙을 기록한다.

---

## 릴리즈 / marketplace 동기화 규칙

이 repo (`token-keeper/cache-necromancer`) 는 marketplace repo (`token-keeper/plugins`) 의 **git submodule** 로 포함되어 있다. submodule 은 특정 commit SHA 를 고정해서 가리키므로, 본체에 push 해도 marketplace 의 pointer 는 자동으로 따라오지 않는다.

따라서 **`main` 에 새 commit 이 올라가면 반드시 marketplace 의 submodule pointer 도 같이 갱신해야 한다.** 안 그러면 marketplace 를 통해 설치하는 사용자는 새 버전을 못 받는다.

### 작업 순서

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

### 진단 시 확인 명령

```bash
# 활성 버전 (진짜 소스)
python3 -c "import json; d=json.load(open('$HOME/.claude/plugins/installed_plugins.json')); print([v for k,v in d['plugins'].items() if 'cache-necromancer' in k])"
# 실제 실행 중인 refresh.py 버전 분포
ps -ef | grep 'cache-necromancer.*refresh.py' | grep -v grep | grep -oE 'cache-necromancer/[0-9.]+/scripts' | sort | uniq -c
```

이 둘이 최신 버전으로 일치해야 반영 완료. 옛날 버전 잔존 process 는 `pkill -f "cache-necromancer/<옛버전>/scripts/refresh.py"` 로 정리 (v0.4.2+ 는 새 fire 시 자동 정리).

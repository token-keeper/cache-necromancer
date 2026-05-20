# cache-necromancer 공개 배포 체크리스트

> alpha → public 전환 작업 진행 상황 추적용. 모든 항목 완료 시 이 문서 삭제 (squash 시점 또는 release 직후).

---

## 단계 1 — cache-necromancer repo 정비 ✅

- [x] `.claude-plugin/marketplace.json` 삭제 (self-marketplace 폐기, token-keeper/plugins 로 이관)
- [x] `.claude-plugin/plugin.json` version 0.3.9 → 0.3.11 sync
- [x] `README.md` 설치 안내 갱신 → `/plugin marketplace add token-keeper/plugins` + `install cache-necromancer@token-keeper`
- [x] author rename: `Brody Byun` → `brody424` (활성 + archive doc 12 파일)
- [x] commit `d19d7ae` + push to origin/main

## 단계 2-pre — Commit history squash (옵션 A) ⚠️ public 전환 직전 실행

> **반드시 private 상태에서 실행.** force push 1회. fork/clone 외부 사용자 없는 alpha 단계라 안전.

- [ ] 현재 main 의 모든 commit 을 orphan branch 에 단일 commit 으로 압축
- [ ] commit 메시지 예: `chore: initial release v0.3.11 — Auto-refresh Claude Code prompt cache TTL via Stop hook + asyncRewake`
- [ ] force push to origin/main

명령 예시:
```bash
# 1. release-checklist.md 제거 (release 시점엔 불필요)
rm docs/release-checklist.md
git add -A && git commit -m "chore: remove release checklist"

# 2. orphan branch 생성 + 단일 commit
git checkout --orphan release/v0.3.11
git add -A
git commit -m "chore: initial release v0.3.11"

# 3. main 으로 force replace
git branch -D main
git branch -M release/v0.3.11 main
git push --force-with-lease origin main
```

## 단계 2 — cache-necromancer repo public 전환

- [ ] visibility 변경:
  ```bash
  gh repo edit token-keeper/cache-necromancer --visibility public --accept-visibility-change-consequences
  ```
  또는 GitHub UI: Settings → Danger Zone → Change visibility → Make public

## 단계 3 — token-keeper/plugins marketplace repo 신설

- [ ] repo 생성:
  ```bash
  gh repo create token-keeper/plugins --public --description "token-keeper Claude Code plugins marketplace"
  ```
- [ ] 로컬 clone

## 단계 4 — marketplace 셋업

- [ ] `.claude-plugin/marketplace.json` 작성 (`name: "token-keeper"`, plugins 배열에 cache-necromancer + token-tracker 등록, `source: "./plugins/<name>"`)
- [ ] `.gitmodules` + submodule 추가:
  ```bash
  git submodule add https://github.com/token-keeper/cache-necromancer.git plugins/cache-necromancer
  git submodule add https://github.com/token-keeper/token-tracker.git plugins/token-tracker
  ```
- [ ] README 작성 (fivetaku/gptaku_plugins 참고)
- [ ] commit + push

## 단계 5 — token-keeper/token-tracker 정리

- [ ] 자체 `.claude-plugin/marketplace.json` 제거 (marketplace 역할 분리, 순수 plugin repo 로 변환)
- [ ] README 설치 안내 갱신 → `/plugin marketplace add token-keeper/plugins`
- [ ] (선택) marketplace.json 에 남아있던 owner email `ghbcw424@gmail.com` 노출도 정리 — token-tracker repo 자체 정리 시 함께 처리
- [ ] commit + push

## 단계 6 — cache-necromancer 영어 README

- [ ] 한글 README 사용자 피드백 반영 후 영어 버전 작성 (`README.en.md` 또는 분리 방식 결정)

## 사후 검증

- [ ] 새 Claude Code 세션에서 `/plugin marketplace add token-keeper/plugins` 동작 확인
- [ ] `/plugin install cache-necromancer@token-keeper` 설치 성공
- [ ] 30분 wake 실제 발생 + cache 100% hit 확인
- [ ] `token-keeper/token-tracker` 도 동일하게 설치/동작 검증

---

## 결정 기록

- **marketplace repo 이름**: `token-keeper/plugins`
- **marketplace.json `name` 필드**: `"token-keeper"` (`/plugin install <plugin>@token-keeper` 로 사용)
- **plugin 호스팅 방식**: monorepo + git submodule (각 plugin repo 그대로 유지, marketplace repo 가 submodule 로 mount)
- **history 정리**: 옵션 A — 전체 squash to 1 commit (private 상태에서 force push)
- **history 정리 시점**: 단계 2 (public 전환) 직전

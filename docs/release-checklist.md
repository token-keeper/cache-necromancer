# cache-necromancer 공개 배포 체크리스트

> alpha → public 전환 작업 진행 상황 추적용. 모든 항목 완료 시 이 문서 삭제.

## 남은 항목

- [ ] `token-keeper/token-tracker` README 설치 안내 갱신 → `/plugin marketplace add token-keeper/plugins` (2026-10-08 확인: 아직 `token-keeper/token-tracker` 자체 marketplace 등록 안내. 작업은 token-tracker repo 에서)

## 정리된 항목 (2026-10-08)

- 완료: repo 정비(단계 1), cache-necromancer·token-tracker·plugins repo public 전환, `token-keeper/plugins` marketplace + submodule 셋업, token-tracker 자체 `marketplace.json` 제거, 영어 README(`README.en.md`).
- 대체: v0.4.0 마일스톤의 `/cn:set key=value` → v0.5.0 `/cn:set N` 소생 예산, `scripts/setup.py` wizard → v0.7.0 `/cn:config` 터미널 TUI. 사후 검증의 `/cn:set mode=auto`·setup.py 항목도 함께 폐기.
- 폐기: commit history squash(단계 2-pre) — private 상태 전제였는데 repo 가 이미 public 이라 force push 대상이 아니다.

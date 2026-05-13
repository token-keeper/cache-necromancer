"""짧은 sid 마스크 헬퍼.

dry-run / status 출력 등 transcript 캡처 가능 위치에서 원본 session_id
(또는 sanitize 통과한 UUID) 가 그대로 노출되지 않도록 8자 prefix만 표시한다.
파일시스템 / 상태 비교에는 원본 sid_hash 를 그대로 사용한다 — 표시 경로
한정 마스킹.
"""


def mask_sid(sid_hash: str) -> str:
    if not sid_hash:
        return "?"
    if len(sid_hash) <= 8:
        return sid_hash
    return sid_hash[:8]

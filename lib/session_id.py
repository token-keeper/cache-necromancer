"""session_id를 파일시스템 안전한 sid_hash로 변환."""
import hashlib
import re

_VALID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def sanitize(session_id: str) -> str:
    """session_id를 파일시스템 안전한 sid_hash로 변환.

    정규식 ``^[a-zA-Z0-9_-]{1,64}$`` 를 통과하면 그대로 반환.
    실패 시 ``sha256(session_id)[:16]`` 을 반환해 경로 traversal과
    파일시스템 제약(길이, 특수문자)을 회피한다.

    Args:
        session_id: hook stdin JSON의 ``session_id`` 필드.

    Returns:
        파일명으로 안전하게 쓸 수 있는 hash.

    Raises:
        ValueError: ``session_id`` 가 빈 문자열인 경우.
    """
    if not session_id:
        raise ValueError("session_id must not be empty")
    if _VALID_PATTERN.match(session_id):
        return session_id
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]

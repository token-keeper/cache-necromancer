"""실제 ``claude -p`` 호출 통합 테스트.

기본적으로 skip된다. 다음 두 조건이 모두 충족돼야 실행:
1. ``claude`` CLI가 PATH에 있음
2. 환경변수 ``CN_INTEGRATION_SESSION_ID`` 에 유효한 활성 세션 ID 설정

활성 세션 ID는 ``--resume`` 가 필요하기 때문에 임의 값으로는 실행 불가.
사용자가 자기 세션 ID를 명시적으로 지정해야 비용/안전성 통제 가능.

수동 실행 예시:
    CN_INTEGRATION_SESSION_ID=<your-session-id> \\
        pytest tests/daemon/test_refresh_integration.py -v
"""
import os
import shutil

import pytest

from lib.config import Config


_HAS_CLAUDE = shutil.which("claude") is not None
_INTEGRATION_SID = os.environ.get("CN_INTEGRATION_SESSION_ID")


pytestmark = pytest.mark.skipif(
    not (_HAS_CLAUDE and _INTEGRATION_SID),
    reason=(
        "통합 테스트 — claude CLI + CN_INTEGRATION_SESSION_ID 환경변수 모두 필요"
    ),
)


def test_fire_returns_cache_read_on_active_session():
    """실제 호출 — cache_read>0 또는 CACHE_COLD 둘 중 하나가 정상 분기."""
    from daemon import refresh

    state = {
        "session_id": _INTEGRATION_SID,
        "sid_hash": _INTEGRATION_SID[:8],
        "cwd": os.getcwd(),
    }
    result = refresh.fire(state, Config())

    # 호출 자체는 성공해야 함 (AUTH_ERROR / PROCESS_ERROR 가 아님)
    assert result.reason in (
        refresh.FireReason.OK,
        refresh.FireReason.CACHE_COLD,
    ), f"unexpected reason={result.reason}, raw={result.raw_stdout!r}"

    # OK 이면 cache_read>0, CACHE_COLD 이면 cache_read==0
    if result.reason is refresh.FireReason.OK:
        assert result.cache_read > 0
        assert result.success is True
    else:
        assert result.cache_read == 0
        assert result.success is False

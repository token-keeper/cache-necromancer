#!/usr/bin/env python3
"""UserPromptExpansion hook — `/cn:status` 슬래시 명령을 LLM turn 없이 처리.

사용자가 `/cn:status` (또는 `/cache-necromancer:cn:status`) 를 입력하면:
  1. command_name 매칭으로 슬래시 명령 식별
  2. cn_status.py 를 subprocess 로 호출 (session_id 환경변수 전파)
  3. 출력 표를 reason 으로 반환 + decision="block"
  4. → Claude Code 가 reason 을 채팅창에 표시. bash dispatcher / LLM turn 모두 미발생.

`/cn:status` 외 다른 입력은 통과 (sys.exit(0) without JSON).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CN_STATUS = _HERE / "cn_status.py"

# 매칭 대상 — short + full namespace 모두 지원
_TARGETS = {"/cn:status", "/cache-necromancer:cn:status"}


def _matches(data: dict) -> bool:
    cmd = (data.get("command_name") or "").strip()
    if cmd:
        # command_name 이 있으면 그것만으로 판정 — prompt fallback 으로 빠지지 않음
        # (다른 slash command 의 prompt 에 우연히 /cn:status 가 들어가는 경우 차단)
        return cmd in {"cn:status", "cache-necromancer:cn:status"}
    # command_name 비어있을 때만 prompt 문자열 fallback
    prompt = (data.get("prompt") or "").strip()
    return prompt in _TARGETS


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not _matches(data):
        return 0

    # session_id 를 subprocess 환경변수로 전파 → (this) 마커 정상 동작
    env = os.environ.copy()
    sid = data.get("session_id")
    if sid:
        env["CLAUDE_CODE_SESSION_ID"] = sid

    try:
        result = subprocess.run(
            ["python3", str(_CN_STATUS)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        output = result.stdout or "(empty)"
        if result.returncode != 0:
            output += f"\n\n[exit {result.returncode}]"
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
    except subprocess.TimeoutExpired:
        output = "cn_status.py 타임아웃 (10초 초과)"
    except Exception as e:
        output = f"cn_status.py 실행 실패: {e}"

    print(json.dumps({"decision": "block", "reason": output}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

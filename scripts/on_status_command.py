#!/usr/bin/env python3
"""UserPromptExpansion hook — `/cn:status` / `/cn:set` 슬래시 명령을 LLM turn 없이 처리.

사용자가 `/cn:status` 또는 `/cn:set N` (또는 namespace 전체 형식) 을 입력하면:
  1. command_name 또는 prompt 로 슬래시 명령 식별 (_route)
  2. 해당 backend script 를 subprocess 로 호출 (session_id 환경변수 전파)
  3. 출력을 reason 으로 반환 + decision="block"
  4. → Claude Code 가 reason 을 채팅창에 표시. bash dispatcher / LLM turn 모두 미발생.

매칭되지 않는 입력은 통과 (sys.exit(0) without JSON).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.install_version import is_latest_install  # noqa: E402

_CN_STATUS = _HERE / "cn_status.py"
_CN_SET = _HERE / "cn_set.py"
_CN_CONFIG = _HERE / "cn_config.py"

_STATUS_NAMES = {"cn:status", "cache-necromancer:cn:status"}
_SET_NAMES = {"cn:set", "cache-necromancer:cn:set"}
_CONFIG_NAMES = {"cn:config", "cache-necromancer:cn:config"}


def _route(data: dict) -> "tuple[Path, list[str]] | None":
    """매칭되는 (script, argv) 반환. 아니면 None.

    command_name 이 있으면 그것만으로 명령 판정 (prompt prefix match 로
    다른 slash command 가 우연히 매칭되는 것 방지).

    cn:set 의 payload shape 는 두 가지를 모두 허용:
      - command_name='cn:set', prompt='2'         (인자만)
      - command_name='cn:set', prompt='/cn:set 2' (슬래시 포함)
    """
    cmd = (data.get("command_name") or "").strip()
    prompt = (data.get("prompt") or "").strip()

    if cmd:
        if cmd in _STATUS_NAMES:
            return _CN_STATUS, []
        if cmd in _CONFIG_NAMES:
            # TUI 는 stdin 이 필요해 hook subprocess 에선 못 띄움 → 런처 안내만(turn 0)
            return _CN_CONFIG, ["--hint"]
        if cmd in _SET_NAMES:
            tokens = prompt.split()
            if tokens and tokens[0].startswith("/"):
                # "/cn:set 2" 형태 — 첫 토큰은 명령, 나머지가 인자
                args = tokens[1:2]
            else:
                # "2" 형태 — 토큰 전체가 인자
                args = tokens[:1]
            return _CN_SET, args
        return None

    # command_name 없을 때만 prompt fallback
    tokens = prompt.split()
    if not tokens:
        return None
    head = tokens[0]
    if head in {"/cn:status", "/cache-necromancer:cn:status"} and len(tokens) == 1:
        return _CN_STATUS, []
    if head in {"/cn:config", "/cache-necromancer:cn:config"}:
        return _CN_CONFIG, ["--hint"]
    if head in {"/cn:set", "/cache-necromancer:cn:set"}:
        return _CN_SET, tokens[1:2]
    return None


def main() -> int:
    if not is_latest_install():
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    routed = _route(data)
    if routed is None:
        return 0

    script, args = routed

    # session_id 를 subprocess 환경변수로 전파 → 마커 정상 동작
    env = os.environ.copy()
    sid = data.get("session_id")
    if sid:
        env["CLAUDE_CODE_SESSION_ID"] = sid

    script_name = script.name
    try:
        result = subprocess.run(
            ["python3", str(script), *args],
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
        output = f"{script_name} 타임아웃 (10초 초과)"
    except Exception as e:
        output = f"{script_name} 실행 실패: {e}"

    print(json.dumps({"decision": "block", "reason": output}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

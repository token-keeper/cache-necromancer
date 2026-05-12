#!/usr/bin/env python3
"""/cn:config 백엔드 — 현재 설정 + 모드 비교 + 변경 방법.

사용자가 첫 설치 후 "내가 어떤 모드인지 / 어떻게 바꾸는지" 즉시 파악할 수 있게
한 화면에 다 보여준다.
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.config import load_config  # noqa: E402
from lib.mode_help import config_change_hint, mode_help_text, mode_label  # noqa: E402


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def main() -> int:
    root = _resolve_root()
    config_path = root / "config.toml"
    config = load_config(config_path)

    print("cache-necromancer 설정")
    print("─" * 30)
    print(f"config 파일: {config_path}")
    if not config_path.exists():
        print("  (없음 — 기본값 사용 중)")
    print()

    print("현재 설정")
    print(f"  mode:              {mode_label(config.mode, config)}")
    print(f"  refresh_interval:  {config.refresh_interval_minutes}분")
    print(f"  max_refresh_count: {config.max_refresh_count}회 (세션당)")
    print(f"  hybrid_wait:       {config.refresh.hybrid_wait_seconds}초")
    print(f"  fire_timeout:      {config.refresh.fire_timeout_seconds}초")
    print(f"  prompt:            {config.refresh.prompt!r}")
    print(f"  terminal_bell:     {config.notify.terminal_bell}")
    print(f"  system_notification: {config.notify.system_notification}")
    print(f"  imminent_threshold: {config.notify.imminent_threshold_minutes}분")
    print()

    print(mode_help_text())
    print()
    print(config_change_hint(config_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

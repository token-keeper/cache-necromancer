"""Plugin enable/install 상태 self-check.

hook scripts와 데몬이 plugin이 disable/uninstall 됐을 때 자동 차단되도록 사용.

읽기 실패(파일 부재, JSON 파싱 오류, 권한 이슈)는 안전 default=True.
파일을 명시적으로 읽어 disabled / not-installed 임을 확인했을 때만 False.
"""
import json
import os
from pathlib import Path

PLUGIN_KEY = "cache-necromancer@cache-necromancer-marketplace"


def _claude_root() -> Path:
    override = os.environ.get("CN_CLAUDE_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def is_plugin_active() -> bool:
    """plugin이 enabledPlugins=True 이고 installed_plugins에 등록되어 있으면 True."""
    root = _claude_root()

    try:
        settings = json.loads((root / "settings.json").read_text())
    except (OSError, json.JSONDecodeError):
        return True
    if not settings.get("enabledPlugins", {}).get(PLUGIN_KEY, False):
        return False

    try:
        installed = json.loads(
            (root / "plugins" / "installed_plugins.json").read_text()
        )
    except (OSError, json.JSONDecodeError):
        return True
    if PLUGIN_KEY not in installed.get("plugins", {}):
        return False

    return True

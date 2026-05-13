"""Shared pytest fixtures."""
import json

import pytest


@pytest.fixture
def cn_root(tmp_path, monkeypatch):
    """임시 ~/.cache-necromancer 디렉토리.

    `CN_ROOT` 환경변수로 lib 모듈들이 사용하는 경로를 override한다.
    """
    root = tmp_path / "cache-necromancer"
    root.mkdir()
    (root / "state").mkdir()
    monkeypatch.setenv("CN_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def _active_plugin_env(tmp_path, monkeypatch):
    """is_plugin_active()가 True를 반환하도록 임시 ~/.claude 환경 격리.

    autouse — 사용자 실제 settings.json에 의존하지 않게 모든 테스트에 적용.
    plugin disabled 동작을 검증하는 테스트는 이 fixture를 override하면 된다.
    """
    root = tmp_path / "claude"
    (root / "plugins").mkdir(parents=True)
    (root / "settings.json").write_text(
        json.dumps(
            {"enabledPlugins": {"cache-necromancer@cache-necromancer-marketplace": True}}
        )
    )
    (root / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"cache-necromancer@cache-necromancer-marketplace": [{}]}}
        )
    )
    monkeypatch.setenv("CN_CLAUDE_ROOT", str(root))
    return root

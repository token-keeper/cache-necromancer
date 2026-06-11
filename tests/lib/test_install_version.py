"""install_version.is_latest_install() 동작 검증.

`__file__` 을 monkeypatch 해서 fake install cache 구조를 시뮬레이션.
실제 install cache 위치는 `~/.claude/plugins/cache/.../cache-necromancer/<ver>/`
이고, lib/install_version.py 의 `parents[1]` 이 `<ver>/` 디렉터리가 된다.

판정 기준은 `<plugins>/installed_plugins.json` 의 활성 installPath.
json 을 못 읽거나 이 plugin 의 entry 가 없으면 기존 방식(cache 내 최대
버전과 비교)으로 fallback 한다.
"""
import json
from pathlib import Path

import pytest

from lib import install_version


def _fake_install_cache(tmp_path: Path, versions: list[str]) -> Path:
    """tmp_path 아래에 `cache-necromancer/<ver>/lib/install_version.py` 구조 생성.

    return: cache-necromancer 디렉터리 Path.
    """
    root = tmp_path / "cache-necromancer"
    for v in versions:
        (root / v / "lib").mkdir(parents=True)
        (root / v / "lib" / "install_version.py").touch()
    return root


def test_latest_version_returns_true(tmp_path, monkeypatch):
    root = _fake_install_cache(tmp_path, ["0.4.0", "0.4.1"])
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.4.1" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is True


def test_older_version_returns_false(tmp_path, monkeypatch):
    root = _fake_install_cache(tmp_path, ["0.4.0", "0.4.1"])
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.4.0" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is False


def test_dev_environment_non_version_dirname_returns_true(tmp_path, monkeypatch):
    """parents[1] 이 'cache-necromancer' (version 패턴 아님) → 통과."""
    repo = tmp_path / "cache-necromancer"
    (repo / "lib").mkdir(parents=True)
    (repo / "lib" / "install_version.py").touch()
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(repo / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is True


def test_single_install_returns_true(tmp_path, monkeypatch):
    """siblings 가 자기 자신뿐이면 latest."""
    root = _fake_install_cache(tmp_path, ["0.4.1"])
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.4.1" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is True


def test_version_compared_as_tuple_not_string(tmp_path, monkeypatch):
    """string sort 면 '0.4.0' > '0.10.0' 이라 잘못된 latest 가 선택됨.
    tuple 비교로 0.10.0 이 latest 여야 함.
    """
    root = _fake_install_cache(tmp_path, ["0.4.0", "0.10.0"])
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.10.0" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is True

    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.4.0" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is False


def test_non_version_siblings_are_ignored(tmp_path, monkeypatch):
    """`__pycache__` 같은 비-version 디렉터리는 siblings 에서 무시."""
    root = _fake_install_cache(tmp_path, ["0.4.1"])
    (root / "__pycache__").mkdir()
    (root / "tmp-dir").mkdir()
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(root / "0.4.1" / "lib" / "install_version.py"),
    )
    assert install_version.is_latest_install() is True


def _fake_plugins_root(
    tmp_path: Path, versions: list[str], active: str | None = None
) -> Path:
    """실제 install cache 전체 구조 생성:
    `<plugins>/cache/<marketplace>/cache-necromancer/<ver>/lib/install_version.py`
    + active 가 주어지면 `<plugins>/installed_plugins.json` 에 활성 pointer 기록.

    return: cache-necromancer 디렉터리 Path.
    """
    plugins = tmp_path / "plugins"
    plugin_dir = plugins / "cache" / "token-keeper" / "cache-necromancer"
    for v in versions:
        (plugin_dir / v / "lib").mkdir(parents=True)
        (plugin_dir / v / "lib" / "install_version.py").touch()
    if active is not None:
        (plugins / "installed_plugins.json").write_text(
            json.dumps(
                {
                    "plugins": {
                        "cache-necromancer@token-keeper": [
                            {
                                "scope": "user",
                                "installPath": str(plugin_dir / active),
                                "version": active,
                            }
                        ]
                    }
                }
            )
        )
    return plugin_dir


def _patch_file(monkeypatch, plugin_dir: Path, version: str) -> None:
    monkeypatch.setattr(
        install_version,
        "__file__",
        str(plugin_dir / version / "lib" / "install_version.py"),
    )


def test_downloaded_but_inactive_newer_version_does_not_gate_active(
    tmp_path, monkeypatch
):
    """cache 에 0.5.1 이 다운로드만 되고 활성 pointer 는 0.5.0 인 경우,
    활성 버전(0.5.0)의 hook 은 침묵하면 안 된다 (v0.5.1 recap 실종 버그)."""
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active="0.5.0")
    _patch_file(monkeypatch, plugin_dir, "0.5.0")
    assert install_version.is_latest_install() is True


def test_stale_session_older_than_active_returns_false(tmp_path, monkeypatch):
    """활성 pointer 가 0.5.1 인데 옛 세션이 0.5.0 hook 을 fire → 침묵."""
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active="0.5.1")
    _patch_file(monkeypatch, plugin_dir, "0.5.0")
    assert install_version.is_latest_install() is False


def test_inactive_newer_version_itself_returns_false(tmp_path, monkeypatch):
    """다운로드만 되고 아직 활성화 안 된 0.5.1 의 script 가 fire 되면 침묵."""
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active="0.5.0")
    _patch_file(monkeypatch, plugin_dir, "0.5.1")
    assert install_version.is_latest_install() is False


def test_missing_plugins_json_falls_back_to_max_version(tmp_path, monkeypatch):
    """installed_plugins.json 이 없으면 기존 방식(최대 버전 비교) fallback."""
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active=None)
    _patch_file(monkeypatch, plugin_dir, "0.5.0")
    assert install_version.is_latest_install() is False
    _patch_file(monkeypatch, plugin_dir, "0.5.1")
    assert install_version.is_latest_install() is True


def test_malformed_plugins_json_falls_back_to_max_version(tmp_path, monkeypatch):
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active=None)
    (plugin_dir.parents[2] / "installed_plugins.json").write_text("not json{")
    _patch_file(monkeypatch, plugin_dir, "0.5.1")
    assert install_version.is_latest_install() is True
    _patch_file(monkeypatch, plugin_dir, "0.5.0")
    assert install_version.is_latest_install() is False


def test_plugins_json_without_this_plugin_falls_back(tmp_path, monkeypatch):
    """json 에 다른 plugin entry 만 있으면 fallback."""
    plugin_dir = _fake_plugins_root(tmp_path, ["0.5.0", "0.5.1"], active=None)
    (plugin_dir.parents[2] / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "other-plugin@somewhere": [
                        {"installPath": str(tmp_path / "elsewhere"), "version": "1.0.0"}
                    ]
                }
            }
        )
    )
    _patch_file(monkeypatch, plugin_dir, "0.5.0")
    assert install_version.is_latest_install() is False

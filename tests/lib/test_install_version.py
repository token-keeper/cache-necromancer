"""install_version.is_latest_install() 동작 검증.

`__file__` 을 monkeypatch 해서 fake install cache 구조를 시뮬레이션.
실제 install cache 위치는 `~/.claude/plugins/cache/.../cache-necromancer/<ver>/`
이고, lib/install_version.py 의 `parents[1]` 이 `<ver>/` 디렉터리가 된다.
"""
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

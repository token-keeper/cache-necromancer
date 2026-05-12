"""Shared pytest fixtures."""
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

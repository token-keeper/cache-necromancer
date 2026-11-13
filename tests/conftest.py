"""Shared pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def cn_root(tmp_path, monkeypatch):
    """임시 ~/.cache-necromancer 디렉토리 (autouse).

    `CN_ROOT` 환경변수로 lib 모듈들이 사용하는 경로를 override한다. 모든 테스트에
    걸어 어떤 테스트도 실제 `~/.cache-necromancer` (marker·cn.log) 에 쓰지 못하게 한다.
    """
    root = tmp_path / "cache-necromancer"
    root.mkdir()
    monkeypatch.setenv("CN_ROOT", str(root))
    return root

"""Tests for lib.logger"""
from datetime import date


def _reload_logger_with(cn_root, monkeypatch):
    """logger 는 쓸 때마다 CN_ROOT 를 읽는다 — autouse cn_root fixture 가 이미 설정."""
    import lib.logger

    return lib.logger


def test_log_info_writes_dated_cn_log(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("hello world")
    today = date.today().isoformat()
    p = cn_root / f"cn.log.{today}"
    assert p.exists()
    content = p.read_text()
    assert "INFO" in content
    assert "hello world" in content


def test_log_warn_writes_with_warn_level(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_warn("careful")
    today = date.today().isoformat()
    content = (cn_root / f"cn.log.{today}").read_text()
    assert "WARN" in content
    assert "careful" in content


def test_log_appends_multiple_lines(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("line 1")
    logger.log_info("line 2")
    logger.log_info("line 3")
    content = (cn_root / f"cn.log.{date.today().isoformat()}").read_text()
    assert content.count("line ") == 3


def test_log_silent_on_oserror(cn_root, monkeypatch, capsys):
    """logger 실패는 caller crash를 일으키면 안 된다 (PRD 불변: hook 실패가 Claude Code에 영향 없음)."""
    logger = _reload_logger_with(cn_root, monkeypatch)
    monkeypatch.setenv("CN_ROOT", str(cn_root / "nonexistent_parent" / "subdir"))

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(logger.Path, "mkdir", lambda *a, **kw: boom())
    logger.log_info("attempt during failure")
    logger.log_warn("attempt during failure")


def test_log_file_permissions_are_private(cn_root, monkeypatch):
    """log 파일은 0600 권한이어야 한다."""
    import stat

    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("test")
    p = cn_root / f"cn.log.{date.today().isoformat()}"
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"log file mode {oct(mode)}, expected 0o600"


def test_cn_root_resolved_on_every_write(tmp_path, monkeypatch):
    """import 뒤 CN_ROOT 를 바꿔도 새 경로에 쓴다 — 테스트가 실제 사용자 로그에 새지 않게."""
    import lib.logger as logger

    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("CN_ROOT", str(a))
    logger.log_info("to a")
    monkeypatch.setenv("CN_ROOT", str(b))
    logger.log_info("to b")
    name = f"cn.log.{date.today().isoformat()}"
    assert "to a" in (a / name).read_text()
    assert "to b" in (b / name).read_text()
    assert "to b" not in (a / name).read_text()

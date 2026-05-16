"""Tests for lib.logger"""
from datetime import date


def _reload_logger_with(cn_root, monkeypatch):
    """logger 모듈을 reload하면서 LOG_DIR을 cn_root로 override."""
    import importlib

    import lib.logger

    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)
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
    monkeypatch.setattr(logger, "LOG_DIR", cn_root / "nonexistent_parent" / "subdir")

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

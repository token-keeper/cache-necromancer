"""Tests for lib.logger"""
from datetime import date, datetime, timezone


def _reload_logger_with(cn_root, monkeypatch):
    """logger 모듈을 reload하면서 LOG_DIR을 cn_root로 override."""
    import importlib

    import lib.logger

    importlib.reload(lib.logger)
    monkeypatch.setattr(lib.logger, "LOG_DIR", cn_root)
    return lib.logger


def test_log_info_writes_dated_daemon_log(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("hello world")
    today = date.today().isoformat()
    p = cn_root / f"daemon.log.{today}"
    assert p.exists()
    content = p.read_text()
    assert "INFO" in content
    assert "hello world" in content


def test_log_warn_writes_with_warn_level(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_warn("careful")
    today = date.today().isoformat()
    content = (cn_root / f"daemon.log.{today}").read_text()
    assert "WARN" in content
    assert "careful" in content


def test_log_fire_writes_to_fire_log(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    now = datetime.now(timezone.utc)
    logger.log_fire(
        sid_hash="abc",
        session_id="abc123",
        model="opus-4-7",
        reason="ok",
        cache_read=45844,
        cache_create=271,
        input_tokens=6,
        output_tokens=253,
        now=now,
    )
    p = cn_root / f"fire.log.{date.today().isoformat()}"
    assert p.exists()
    line = p.read_text().strip()
    assert "sid=abc" in line
    assert "cache_read=45844" in line
    assert "cache_create=271" in line
    assert "input=6" in line
    assert "output=253" in line
    assert "reason=ok" in line
    assert "model=opus-4-7" in line


def test_log_fire_no_sensitive_data(cn_root, monkeypatch):
    """사용자 프롬프트 내용 / cwd / 경로는 절대 기록되면 안 됨."""
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_fire(
        sid_hash="abc",
        session_id="abc123",
        model="opus-4-7",
        reason="ok",
        cache_read=100,
        cache_create=0,
        input_tokens=5,
        output_tokens=10,
        now=datetime.now(timezone.utc),
    )
    line = (cn_root / f"fire.log.{date.today().isoformat()}").read_text()
    # 절대 포함되면 안 되는 키워드
    assert "cwd" not in line.lower()
    assert "prompt" not in line.lower()
    assert "/users/" not in line.lower()


def test_log_user_turn_writes_to_user_turn_log(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    usage = {
        "model": "opus-4-7",
        "cache_read_input_tokens": 45844,
        "cache_creation_input_tokens": 125,
        "input_tokens": 8,
        "output_tokens": 512,
    }
    logger.log_user_turn(
        sid_hash="abc",
        session_id="abc123",
        usage=usage,
        after_fire=True,
        now=datetime.now(timezone.utc),
    )
    p = cn_root / f"user_turn.log.{date.today().isoformat()}"
    assert p.exists()
    line = p.read_text().strip()
    assert "sid=abc" in line
    assert "cache_read=45844" in line
    assert "after_fire=true" in line


def test_log_user_turn_after_fire_false(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    usage = {
        "model": "opus-4-7",
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 50,
        "input_tokens": 5,
        "output_tokens": 20,
    }
    logger.log_user_turn(
        sid_hash="abc",
        session_id="abc123",
        usage=usage,
        after_fire=False,
        now=datetime.now(timezone.utc),
    )
    line = (cn_root / f"user_turn.log.{date.today().isoformat()}").read_text()
    assert "after_fire=false" in line


def test_log_appends_multiple_lines(cn_root, monkeypatch):
    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("line 1")
    logger.log_info("line 2")
    logger.log_info("line 3")
    content = (cn_root / f"daemon.log.{date.today().isoformat()}").read_text()
    assert content.count("line ") == 3


def test_log_silent_on_oserror(cn_root, monkeypatch, capsys):
    """logger 실패는 caller crash를 일으키면 안 된다 (PRD 불변: hook 실패가 Claude Code에 영향 없음)."""
    logger = _reload_logger_with(cn_root, monkeypatch)
    # 쓰기 불가능한 경로로 LOG_DIR override
    monkeypatch.setattr(logger, "LOG_DIR", cn_root / "nonexistent_parent" / "subdir")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(logger.Path, "mkdir", lambda *a, **kw: boom())
    # OSError 발생해도 예외 전파 안 되어야 함
    logger.log_info("attempt during failure")
    logger.log_warn("attempt during failure")


def test_log_user_turn_no_sensitive_data(cn_root, monkeypatch):
    """user_turn log도 fire log와 동일하게 민감정보 미기록."""
    logger = _reload_logger_with(cn_root, monkeypatch)
    usage = {
        "model": "opus-4-7",
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 50,
        "input_tokens": 5,
        "output_tokens": 20,
    }
    logger.log_user_turn(
        sid_hash="abc",
        session_id="abc123",
        usage=usage,
        after_fire=True,
        now=datetime.now(timezone.utc),
    )
    line = (cn_root / f"user_turn.log.{date.today().isoformat()}").read_text()
    assert "cwd" not in line.lower()
    assert "prompt" not in line.lower()
    assert "/users/" not in line.lower()


def test_log_file_permissions_are_private(cn_root, monkeypatch):
    """log 파일은 0600 권한이어야 한다."""
    import stat

    logger = _reload_logger_with(cn_root, monkeypatch)
    logger.log_info("test")
    p = cn_root / f"daemon.log.{date.today().isoformat()}"
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"log file mode {oct(mode)}, expected 0o600"

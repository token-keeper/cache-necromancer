"""Tests for lib.lockfile"""
import json
import os

import pytest

from lib.lockfile import (
    acquire_daemon_lock,
    is_daemon_alive,
    proc_start_time,
)


def test_proc_start_time_self():
    """현재 프로세스의 start_time을 반환."""
    s = proc_start_time(os.getpid())
    assert s is not None and len(s) > 0


def test_proc_start_time_dead_process():
    """존재하지 않는 PID는 None."""
    assert proc_start_time(999999) is None


def test_is_daemon_alive_missing_file(tmp_path):
    assert is_daemon_alive(tmp_path / "missing.lock") is False


def test_is_daemon_alive_empty_file(tmp_path):
    p = tmp_path / "empty.lock"
    p.touch()
    assert is_daemon_alive(p) is False


def test_is_daemon_alive_invalid_json(tmp_path):
    p = tmp_path / "bad.lock"
    p.write_text("not-json")
    assert is_daemon_alive(p) is False


def test_is_daemon_alive_valid_self(tmp_path):
    """현재 프로세스의 PID + start_time을 기록한 파일은 alive."""
    p = tmp_path / "self.lock"
    pid = os.getpid()
    p.write_text(
        json.dumps({"pid": pid, "started": proc_start_time(pid)})
    )
    assert is_daemon_alive(p) is True


def test_is_daemon_alive_pid_reuse_mismatch(tmp_path):
    """동일 PID이지만 start_time이 다르면 stale."""
    p = tmp_path / "stale.lock"
    p.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started": "Fri Jan  1 00:00:00 1970",
            }
        )
    )
    assert is_daemon_alive(p) is False


def test_is_daemon_alive_dead_pid(tmp_path):
    p = tmp_path / "dead.lock"
    p.write_text(
        json.dumps({"pid": 999999, "started": "Fri Jan  1 00:00:00 1970"})
    )
    assert is_daemon_alive(p) is False


def test_acquire_daemon_lock_success(tmp_path):
    f = acquire_daemon_lock(tmp_path / "d.lock")
    assert f is not None
    # PID + start_time 기록 확인
    f.seek(0)
    content = f.read()
    meta = json.loads(content)
    assert meta["pid"] == os.getpid()
    assert meta["started"] is not None
    f.close()


def test_acquire_daemon_lock_blocks_second_acquire(tmp_path):
    p = tmp_path / "d.lock"
    f1 = acquire_daemon_lock(p)
    assert f1 is not None
    f2 = acquire_daemon_lock(p)
    assert f2 is None  # 이미 alive
    f1.close()


def test_acquire_daemon_lock_recovers_stale(tmp_path):
    """stale lock 파일이 있으면 정리하고 새로 획득."""
    p = tmp_path / "d.lock"
    # 죽은 PID로 stale 락 시뮬레이션
    p.write_text(json.dumps({"pid": 999999, "started": "stale"}))
    f = acquire_daemon_lock(p)
    assert f is not None
    meta = json.loads(p.read_text())
    assert meta["pid"] == os.getpid()
    f.close()

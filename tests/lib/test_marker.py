"""Tests for lib/marker.py — atomic write, concurrent safety, stale cleanup.

TECH_SPEC §11.1 의 marker.py 행 assertion 따름.
"""
import json
import os
import threading
import time

import pytest

from lib.marker import Marker, cleanup_stale, marker_dir, marker_path


class TestLoadSave:
    def test_load_missing_returns_empty_marker(self, cn_root):
        m = Marker.load("abc123")
        assert m.sid_hash == "abc123"
        assert m.latest_fire == 0
        assert m.wake_count == 0
        assert m.last_wake_at == 0
        # 빈 marker 도 session_started_at 은 현재 시각으로 초기화
        assert m.session_started_at > 0

    def test_save_then_load_round_trip(self, cn_root):
        m = Marker(
            sid_hash="abc123",
            latest_fire=1000,
            wake_count=3,
            last_wake_at=999,
            session_started_at=500,
            last_prompt="진행 중인 작업 메모",
        )
        m.save()
        loaded = Marker.load("abc123")
        assert loaded.sid_hash == "abc123"
        assert loaded.latest_fire == 1000
        assert loaded.wake_count == 3
        assert loaded.last_wake_at == 999
        assert loaded.session_started_at == 500
        assert loaded.last_prompt == "진행 중인 작업 메모"

    def test_load_legacy_marker_without_last_prompt(self, cn_root):
        """v0.3.4 이전 marker file (last_prompt 필드 없음) 백워드 호환 — 빈 string default."""
        marker_dir().mkdir(parents=True, exist_ok=True)
        marker_path("legacy").write_text(
            json.dumps({
                "latest_fire": 100,
                "wake_count": 1,
                "last_wake_at": 50,
                "session_started_at": 10,
                # last_prompt 키 의도적 없음
            }),
            encoding="utf-8",
        )
        loaded = Marker.load("legacy")
        assert loaded.latest_fire == 100
        assert loaded.last_prompt == ""

    def test_load_corrupt_json_returns_empty(self, cn_root):
        marker_dir().mkdir(parents=True, exist_ok=True)
        marker_path("abc123").write_text("{invalid json", encoding="utf-8")
        m = Marker.load("abc123")
        assert m.latest_fire == 0
        assert m.wake_count == 0

    def test_load_schema_corrupt_returns_empty(self, cn_root):
        """JSON valid 지만 field type 이 잘못된 케이스 (예: wake_count='bad') 도 빈 marker."""
        marker_dir().mkdir(parents=True, exist_ok=True)
        marker_path("abc123").write_text(
            json.dumps({"latest_fire": "not_int", "wake_count": "bad"}),
            encoding="utf-8",
        )
        m = Marker.load("abc123")
        assert m.latest_fire == 0
        assert m.wake_count == 0

    def test_delete_idempotent(self, cn_root):
        m = Marker(sid_hash="abc123", latest_fire=100)
        m.save()
        assert marker_path("abc123").exists()
        m.delete()
        assert not marker_path("abc123").exists()
        # idempotent — 두 번 호출해도 안전
        m.delete()


class TestAtomicWrite:
    def test_concurrent_writers_no_corruption(self, cn_root):
        """N writer 동시 → 최종 파일 valid JSON + load 실패 0건."""
        n_writers = 20
        errors: list = []

        def writer(i: int) -> None:
            try:
                Marker(sid_hash="abc123", latest_fire=i, wake_count=i).save()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"writer errors: {errors}"
        loaded = Marker.load("abc123")
        # 최종 marker 가 valid JSON 으로 load 됨 (값은 race 결과 어느 writer 든 OK)
        assert 0 <= loaded.latest_fire < n_writers

    def test_concurrent_writers_and_readers_atomic(self, cn_root):
        """N writer + N reader 동시 → 모든 read 가 valid JSON + 4 field 완전 + 허용된 snapshot.

        atomic write 의 핵심 보장:
          1. read 가 partial JSON 을 절대 보지 않음
          2. read 결과는 항상 4 field 모두 포함 (schema 완전 snapshot)
          3. read 의 latest_fire 는 어떤 writer 가 쓴 값이거나 초기 0
        """
        n_writers = 5
        n_iterations = 50  # 각 writer 가 진행할 라운드
        n_readers = 5
        required_fields = {"latest_fire", "wake_count", "last_wake_at", "session_started_at"}

        errors: list = []
        invalid_reads: list = []
        write_done = threading.Barrier(n_writers + 1)

        Marker(sid_hash="abc123", latest_fire=0).save()

        # 각 writer 가 사용한 latest_fire 값들 — read 검증용
        writer_values = set()
        writer_lock = threading.Lock()

        def writer(writer_id: int) -> None:
            try:
                for i in range(n_iterations):
                    val = writer_id * 1000 + i  # 고유 식별자
                    with writer_lock:
                        writer_values.add(val)
                    Marker(sid_hash="abc123", latest_fire=val, wake_count=writer_id).save()
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                write_done.wait()

        def reader() -> None:
            try:
                while True:
                    try:
                        text = marker_path("abc123").read_text(encoding="utf-8")
                        data = json.loads(text)  # partial 이면 raise
                        # schema 완전성 검증
                        missing = required_fields - data.keys()
                        if missing:
                            invalid_reads.append(f"missing fields: {missing}")
                        else:
                            # latest_fire 가 0 (초기) 또는 writer 가 쓴 값
                            lf = data["latest_fire"]
                            with writer_lock:
                                seen = lf == 0 or lf in writer_values
                            if not seen:
                                invalid_reads.append(f"unknown latest_fire: {lf}")
                    except FileNotFoundError:
                        pass  # save 직전 race
                    except json.JSONDecodeError as e:
                        invalid_reads.append(f"partial JSON: {e}")
                    except OSError:
                        pass
                    if write_done.n_waiting == n_writers:
                        # writer 들이 모두 끝나기 직전 — 한 번 더 read 후 종료
                        try:
                            data = json.loads(
                                marker_path("abc123").read_text(encoding="utf-8")
                            )
                            if required_fields - data.keys():
                                invalid_reads.append(
                                    f"final read missing fields: {data.keys()}"
                                )
                        except (json.JSONDecodeError, OSError) as e:
                            invalid_reads.append(f"final read fail: {e}")
                        return
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        reader_threads = [threading.Thread(target=reader) for _ in range(n_readers)]
        writer_threads = [
            threading.Thread(target=writer, args=(i,)) for i in range(n_writers)
        ]
        for t in reader_threads:
            t.start()
        for t in writer_threads:
            t.start()
        write_done.wait()  # writer 모두 끝남 (reader 가 detect 후 종료)
        for t in writer_threads:
            t.join()
        for t in reader_threads:
            t.join(timeout=2.0)

        assert not errors, f"thread errors: {errors}"
        assert not invalid_reads, (
            f"reader 가 partial/incomplete JSON 봄 — atomic write 실패: {invalid_reads[:5]}"
        )


class TestSaveFailure:
    @pytest.mark.skipif(
        os.geteuid() == 0,
        reason="root 는 chmod 0o400 무시하므로 권한 에러 검증 불가",
    )
    def test_save_raises_on_permission_denied(self, cn_root):
        """권한 에러 시 OSError raise (호출자가 catch 해서 graceful 처리)."""
        d = marker_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o400)
        try:
            with pytest.raises(OSError):
                Marker(sid_hash="abc123", latest_fire=1).save()
        finally:
            os.chmod(d, 0o700)

    def test_save_failure_preserves_existing_marker(self, cn_root, monkeypatch):
        """저장 실패 시 기존 marker file 그대로 보존 (TECH_SPEC §3.1 graceful degradation)."""
        Marker(sid_hash="abc123", latest_fire=100, wake_count=5).save()

        def fake_replace(*args, **kwargs):
            raise OSError("simulated ENOSPC")

        monkeypatch.setattr("lib.marker.os.replace", fake_replace)

        with pytest.raises(OSError):
            Marker(sid_hash="abc123", latest_fire=999, wake_count=99).save()

        # 기존 marker 그대로
        loaded = Marker.load("abc123")
        assert loaded.latest_fire == 100
        assert loaded.wake_count == 5


class TestCleanupStale:
    def test_deletes_files_older_than_threshold(self, cn_root):
        d = marker_dir()
        d.mkdir(parents=True, exist_ok=True)
        old = d / "old.json"
        new = d / "new.json"
        old.write_text("{}", encoding="utf-8")
        new.write_text("{}", encoding="utf-8")
        # old 의 mtime 을 8일 전으로
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))

        deleted = cleanup_stale(max_age_seconds=7 * 86400)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_returns_zero_when_marker_dir_missing(self, cn_root):
        deleted = cleanup_stale()
        assert deleted == 0

    def test_returns_zero_when_no_stale_files(self, cn_root):
        d = marker_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "fresh.json").write_text("{}", encoding="utf-8")
        deleted = cleanup_stale()
        assert deleted == 0

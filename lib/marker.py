"""Per-session marker file (`~/.cache-necromancer/marker/<sid_hash>.json`).

TECH_SPEC §3.1 — atomic write 로 동시 read/write 안전성 보장.
저장 실패 시 호출자가 catch (graceful degradation).
"""
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".cache-necromancer"


def marker_dir() -> Path:
    return _resolve_root() / "marker"


def marker_path(sid_hash: str) -> Path:
    return marker_dir() / f"{sid_hash}.json"


@dataclass
class Marker:
    """Marker file 의 in-memory representation.

    Fields (TECH_SPEC §3.1):
      - latest_fire: 가장 최근 Stop hook fire 시각 (Unix timestamp)
      - wake_count: 누적 wake 또는 notify 횟수 (mode 무관)
      - last_wake_at: 직전 wake/notify 시각
      - session_started_at: 세션 시작 시각
    """
    sid_hash: str
    latest_fire: int = 0
    wake_count: int = 0
    last_wake_at: int = 0
    session_started_at: int = 0

    @classmethod
    def load(cls, sid_hash: str) -> "Marker":
        """marker file 에서 로드. 없거나 corrupt (JSON syntax/schema) 시 빈 marker."""
        path = marker_path(sid_hash)
        if not path.exists():
            return cls(sid_hash=sid_hash, session_started_at=int(time.time()))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                sid_hash=sid_hash,
                latest_fire=int(data.get("latest_fire", 0)),
                wake_count=int(data.get("wake_count", 0)),
                last_wake_at=int(data.get("last_wake_at", 0)),
                session_started_at=int(
                    data.get("session_started_at", int(time.time()))
                ),
            )
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return cls(sid_hash=sid_hash, session_started_at=int(time.time()))

    def save(self) -> None:
        """Atomic write — `tempfile + os.replace()` POSIX 원자성 보장.

        Raises:
            OSError: 권한 거부 / 디스크 풀 (ENOSPC) / tempfile 생성 실패 등.
                호출자가 catch 해서 graceful degradation 처리 (log + exit 0).
                실패 시 기존 marker file 은 그대로 보존됨 (replace 가 일어나지 않음).
        """
        dir_ = marker_dir()
        dir_.mkdir(parents=True, exist_ok=True)
        body = {
            "latest_fire": self.latest_fire,
            "wake_count": self.wake_count,
            "last_wake_at": self.last_wake_at,
            "session_started_at": self.session_started_at,
        }
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=dir_,
                prefix=f".{self.sid_hash}.",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(body, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, marker_path(self.sid_hash))
            tmp_path = None
            # 디렉터리 fsync — 전원 장애 시 디렉터리 엔트리 보존 (best-effort, 실패 silent)
            try:
                dir_fd = os.open(dir_, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            # replace 실패 시 tempfile cleanup
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def delete(self) -> None:
        """marker file 삭제. 없으면 silent."""
        marker_path(self.sid_hash).unlink(missing_ok=True)


def cleanup_stale(max_age_seconds: int = 7 * 86400) -> int:
    """marker_dir 의 7일 초과 stale file 정리. 삭제 개수 반환.

    on_session_end.py 가 매 SessionEnd 에서 호출 (TECH_SPEC §6).
    """
    dir_ = marker_dir()
    if not dir_.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    deleted = 0
    for path in dir_.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
        except OSError:
            continue
    return deleted

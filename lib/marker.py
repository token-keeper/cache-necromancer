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

    Fields (v0.12.0):
      - latest_fire: 마지막 Stop 시각 (ns). on_recap.py 만 기록. refresh.py 의 사용자
        활동·억제 판정과 cn_set·cn_status 생존 시각의 기준 (Python 은 mod 의 base 를 모름).
      - wake_count: 이번 자리비움에 실제로 깨운 횟수. 진짜 사용자 입력 때 0.
      - last_wake_at: 마지막 깨우기 (초, 표시·복귀 로그용)
      - last_wake_at_ns: 마지막 깨우기 (ns) — 복귀 판정은 이걸로
      - last_prompt: 가장 최근 user prompt (40자 truncate, /cn:status 의
        세션 식별용). PRD §8 도구 정신 예외: marker 0600 권한 +
        본인 환경 한정 노출 (single-user alpha 가정).
      - cwd: 가장 최근 user prompt 의 작업 디렉터리 (/cn:status 의 다른 세션 식별용).
      - last_user_activity_at_ns: 마지막 진짜 사용자 입력 시각 (ns). PING·
        task-notification·피어/팀메이트 메시지·/cn: 명령은 제외.
      - last_turn_start_at_ns: 마지막 turn 시작 시각 (ns). PING·/cn: 명령을 뺀 모든
        prompt(task-notification·피어/팀메이트 메시지 포함). refresh.py 의 "진행 중
        turn" 판정용 — 사용자 활동이 아니어도 turn 은 돈다.
      - set_budget_remaining / set_budget_total / set_charged_at_ns: /cn:set N —
        이번 자리비움 깨우기 횟수 덮어쓰기 (남은 수 / 충전량 / 충전 시각 ns).
        충전 뒤 깨운 적이 있으면 사용자 복귀 때 0 으로 비워진다.
      - wake_off: /cn:set 0·off — 세션 끝까지 깨우기 끔. /cn:set N(≥1)·시간 충전·auto(패널 [자동]) 가 해제.
      - suppressed_at_ns: SessionStart(clear|compact) 가 기록하는 억제 시각 (ns).
        max(last_user_activity_at_ns, latest_fire) 보다 크면 refresh.py 가 skip.
    """
    sid_hash: str
    latest_fire: int = 0
    wake_count: int = 0
    last_wake_at: int = 0
    last_wake_at_ns: int = 0
    last_prompt: str = ""
    cwd: str = ""
    last_user_activity_at_ns: int = 0
    last_turn_start_at_ns: int = 0
    set_budget_remaining: int = 0
    set_budget_total: int = 0
    set_charged_at_ns: int = 0
    wake_off: bool = False
    suppressed_at_ns: int = 0

    @classmethod
    def load(cls, sid_hash: str) -> "Marker":
        """marker file 에서 로드. 없거나 corrupt (JSON syntax/schema) 시 빈 marker."""
        path = marker_path(sid_hash)
        if not path.exists():
            return cls(sid_hash=sid_hash)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                sid_hash=sid_hash,
                latest_fire=int(data.get("latest_fire", 0)),
                wake_count=int(data.get("wake_count", 0)),
                last_wake_at=int(data.get("last_wake_at", 0)),
                # v0.11 marker 는 초 단위 last_wake_at 만 있다 — 키가 없을 때만 초로 채움
                last_wake_at_ns=(
                    int(data["last_wake_at_ns"]) if "last_wake_at_ns" in data
                    else int(data.get("last_wake_at", 0)) * 1_000_000_000
                ),
                last_prompt=str(data.get("last_prompt", "")),
                cwd=str(data.get("cwd", "")),
                last_user_activity_at_ns=int(
                    data.get("last_user_activity_at_ns", 0)
                ),
                last_turn_start_at_ns=int(data.get("last_turn_start_at_ns", 0)),
                set_budget_remaining=int(data.get("set_budget_remaining", 0)),
                set_budget_total=int(data.get("set_budget_total", 0)),
                set_charged_at_ns=int(data.get("set_charged_at_ns", 0)),
                wake_off=data.get("wake_off") is True,
                suppressed_at_ns=int(data.get("suppressed_at_ns", 0)),
            )
        except (json.JSONDecodeError, OSError, ValueError, TypeError, AttributeError):
            return cls(sid_hash=sid_hash)

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
            "last_wake_at_ns": self.last_wake_at_ns,
            "last_prompt": self.last_prompt,
            "cwd": self.cwd,
            "last_user_activity_at_ns": self.last_user_activity_at_ns,
            "last_turn_start_at_ns": self.last_turn_start_at_ns,
            "set_budget_remaining": self.set_budget_remaining,
            "set_budget_total": self.set_budget_total,
            "set_charged_at_ns": self.set_charged_at_ns,
            "wake_off": self.wake_off,
            "suppressed_at_ns": self.suppressed_at_ns,
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

"""install cache 의 latest 버전 self-gate.

Claude Code plugin 시스템은 hook command 경로를 register 시점의 절대경로로
박고, plugin 이 update 되어도 옛날 세션의 register 는 그대로 살아있다.
그래서 marketplace 가 N+1 로 bump 된 후에도 옛날 세션이 N 의 hook script 를
계속 fire 시켜 옛날 코드가 알림을 띄우거나 marker 를 옛날 schema 로
덮어쓸 수 있다.

각 hook entry point 가 진입부에서 is_latest_install() 을 호출해
"내가 install cache 의 latest 버전인지" 확인한다. 아니면 조용히 exit.

dev source / pip install 처럼 install cache 가 아닌 환경에선 True 반환 (통과).
"""
import pathlib


def is_latest_install() -> bool:
    """현재 실행 중인 script 의 디렉터리가 install cache 의 latest 버전인지."""
    my_dir = pathlib.Path(__file__).resolve().parents[1]
    if not _looks_like_version(my_dir.name):
        return True
    parent = my_dir.parent
    try:
        siblings = [
            p for p in parent.iterdir()
            if p.is_dir() and _looks_like_version(p.name)
        ]
    except OSError:
        return True
    if not siblings:
        return True
    latest = max(siblings, key=lambda p: _parse_version(p.name))
    return my_dir.resolve() == latest.resolve()


def _looks_like_version(name: str) -> bool:
    parts = name.split(".")
    return 2 <= len(parts) <= 4 and all(p.isdigit() for p in parts)


def _parse_version(name: str) -> tuple:
    return tuple(int(x) for x in name.split("."))

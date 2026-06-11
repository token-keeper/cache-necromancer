"""install cache 의 활성 버전 self-gate.

Claude Code plugin 시스템은 hook command 경로를 register 시점의 절대경로로
박고, plugin 이 update 되어도 옛날 세션의 register 는 그대로 살아있다.
그래서 marketplace 가 N+1 로 bump 된 후에도 옛날 세션이 N 의 hook script 를
계속 fire 시켜 옛날 코드가 알림을 띄우거나 marker 를 옛날 schema 로
덮어쓸 수 있다.

각 hook entry point 가 진입부에서 is_latest_install() 을 호출해
"내가 활성 install 인지" 확인한다. 아니면 조용히 exit.

판정 기준은 `<plugins>/installed_plugins.json` 의 활성 installPath.
"cache 내 최대 버전 디렉터리" 비교는 fallback 으로만 쓴다 — 그 기준을
주 판정으로 쓰면 /reload-plugins 가 새 버전을 다운로드만 해놓은 상태
(활성 pointer 는 그대로)에서 활성 버전의 hook 까지 전부 침묵하는
오발동이 난다 (v0.5.0 에서 실제 발생: recap 실종).

dev source / pip install 처럼 install cache 가 아닌 환경에선 True 반환 (통과).
"""
import json
import pathlib


def is_latest_install() -> bool:
    """현재 실행 중인 script 의 디렉터리가 활성 install 인지."""
    my_dir = pathlib.Path(__file__).resolve().parents[1]
    if not _looks_like_version(my_dir.name):
        return True
    active = _check_active_install(my_dir)
    if active is not None:
        return active
    # fallback: installed_plugins.json 을 못 읽거나 이 plugin 의 entry 가
    # 없으면 기존 방식 — install cache 의 최대 버전 디렉터리와 비교.
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


def _check_active_install(my_dir: pathlib.Path) -> bool | None:
    """installed_plugins.json 기준으로 my_dir 가 활성 install 인지.

    구조: `<plugins>/cache/<marketplace>/<plugin>/<version>/` 이므로
    json 은 `my_dir.parents[3]/installed_plugins.json`.

    return: True/False = 판정 성공, None = 판정 불가 (호출측 fallback).
    """
    try:
        data = json.loads(
            (my_dir.parents[3] / "installed_plugins.json").read_text()
        )
        plugin_dir = my_dir.parent
        found = False
        for entries in data["plugins"].values():
            if not isinstance(entries, list):
                entries = [entries]
            for entry in entries:
                path = pathlib.Path(entry["installPath"]).resolve()
                if path.parent == plugin_dir:
                    found = True
                    if path == my_dir:
                        return True
        return False if found else None
    except (OSError, IndexError, KeyError, TypeError, ValueError):
        return None


def _looks_like_version(name: str) -> bool:
    parts = name.split(".")
    return 2 <= len(parts) <= 4 and all(p.isdigit() for p in parts)


def _parse_version(name: str) -> tuple:
    return tuple(int(x) for x in name.split("."))

"""`cn install` / `cn uninstall` CLI (TECH_SPEC §7).

Plugin marketplace 사용자는 `/plugin install cache-necromancer` 한 명령이면
자동으로 hook 등록되므로 이 CLI 는 fallback 용 — 직접 git clone + venv setup
환경에서 settings.json 에 hook 을 수동 등록하는 사용자용.

동작:
  - install: stale v0.2.x daemon 안내 + settings.json 에 hook 추가
  - uninstall: settings.json 에서 cache-necromancer 관련 hook 제거
"""
import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

# 절대 경로 마커 — 다른 cache-necromancer fork 와 substring 충돌 방지
CN_HOOK_MARKER = str(_PROJECT_ROOT / "scripts/refresh.py")


def _resolve_cn_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _resolve_claude_root() -> Path:
    root = os.environ.get("CN_CLAUDE_ROOT")
    return Path(root) if root else Path.home() / ".claude"


def _settings_path() -> Path:
    return _resolve_claude_root() / "settings.json"


def _detect_stale_daemon(out) -> bool:
    """v0.2.x daemon lock + state file detect. 발견 시 stdout 에 정리 안내."""
    cn_root = _resolve_cn_root()
    found = []
    lock = cn_root / "lock"
    if lock.exists():
        found.append(f"  - {lock}")
    state_dir = cn_root / "state"
    if state_dir.exists() and any(state_dir.iterdir()):
        found.append(f"  - {state_dir} (디렉토리)")
    if not found:
        return False
    print("⚠️  v0.2.x daemon 잔존 파일 감지 — 다음 명령으로 직접 정리하세요:", file=out)
    for f in found:
        print(f, file=out)
    print(
        "  $ pkill -f 'python.*-m daemon' || true\n"
        "  $ rm -rf ~/.cache-necromancer/lock ~/.cache-necromancer/state",
        file=out,
    )
    return True


def _detect_deprecated_config(out) -> None:
    """config.toml 의 v0.2.x 폐기 옵션 안내. lib.config._warn_deprecated 가 stderr 로
    경고하지만 cn install 이 한 번 더 명시적으로 알림.
    """
    cfg = _resolve_cn_root() / "config.toml"
    if not cfg.exists():
        return
    from lib.config import load_config

    try:
        load_config(cfg)
    except ValueError:
        print(
            f"⚠️  config.toml 의 mode 값이 invalid 합니다: {cfg}",
            file=out,
        )


def _ensure_config_file(out) -> None:
    """config.toml 없으면 기본 템플릿 생성 + 안내 (PRD §3.2)."""
    from lib.config import ensure_config_file

    cfg = _resolve_cn_root() / "config.toml"
    existed = cfg.exists()
    try:
        ensure_config_file(cfg)
    except OSError as e:
        print(f"⚠️  config.toml 생성 실패: {e}", file=out)
        return
    if not existed and cfg.exists():
        print(f"📝 config.toml 자동 생성됨: {cfg}", file=out)


def _refresh_command() -> str:
    """settings.json 에 등록할 command."""
    return f'python3 "{_PROJECT_ROOT}/scripts/refresh.py"'


def _hook_entry() -> dict:
    """settings.json 의 Stop hook entry 구조 (hooks/hooks.json 과 동일)."""
    return {
        "hooks": [
            {
                "type": "command",
                "command": _refresh_command(),
                "asyncRewake": True,
                "timeout": 3600,
            }
        ]
    }


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  settings.json 파싱 실패: {e}. 진행하지 않습니다.", file=sys.stderr)
        raise


def _save_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _has_cn_hook(stop_hooks: list) -> bool:
    for entry in stop_hooks:
        for hook in entry.get("hooks", []):
            if CN_HOOK_MARKER in hook.get("command", ""):
                return True
    return False


def _has_other_stop_hooks(stop_hooks: list) -> bool:
    for entry in stop_hooks:
        for hook in entry.get("hooks", []):
            if CN_HOOK_MARKER not in hook.get("command", ""):
                return True
    return False


def install_main(force: bool = False, out=None, err=None) -> int:
    """settings.json 에 cache-necromancer Stop hook 등록.

    Args:
        force: 다른 Stop hook 가 있어도 prompt 없이 추가.
    """
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    _detect_stale_daemon(out)
    _ensure_config_file(out)
    _detect_deprecated_config(err)

    sp = _settings_path()
    try:
        settings = _load_settings(sp)
    except (json.JSONDecodeError, OSError):
        return 1

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    if _has_cn_hook(stop_hooks):
        print(f"✅ 이미 설치됨: {sp}", file=out)
        return 0

    if _has_other_stop_hooks(stop_hooks) and not force:
        print(
            f"⚠️  기존 Stop hook 가 settings.json 에 있습니다 ({sp}).\n"
            "    공존 시 중복 fire 가능. 계속하려면 `cn install --force`.",
            file=err,
        )
        return 1

    stop_hooks.append(_hook_entry())
    _save_settings(sp, settings)

    print(f"✅ 설치 완료: {sp}", file=out)
    print(
        "ℹ️  Claude Code 는 settings hot-reload 안 함 — 새 chat 세션을 시작해야 적용.\n"
        "ℹ️  v0.2.x 사용자 주의: refresh_interval_minutes default 가 55 → 50 으로 변경.\n"
        "   기존 config.toml 의 명시적 값은 그대로 유지됨.",
        file=out,
    )
    return 0


def uninstall_main(out=None, err=None) -> int:
    """settings.json 에서 cache-necromancer 관련 Stop hook 만 제거.

    다른 hook 은 그대로 보존. config.toml 과 marker file 은 삭제 X
    (사용자가 수동으로 `rm -rf ~/.cache-necromancer` 가능).
    """
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    sp = _settings_path()
    if not sp.exists():
        print(f"ℹ️  settings.json 없음: {sp}", file=out)
        return 0

    try:
        settings = _load_settings(sp)
    except (json.JSONDecodeError, OSError):
        return 1

    hooks = settings.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])
    if not stop_hooks:
        print(f"ℹ️  Stop hook 없음 — 변경 X: {sp}", file=out)
        return 0

    new_stop = []
    removed = 0
    for entry in stop_hooks:
        kept = [h for h in entry.get("hooks", []) if CN_HOOK_MARKER not in h.get("command", "")]
        removed += len(entry.get("hooks", [])) - len(kept)
        if kept:
            new_stop.append({**entry, "hooks": kept})

    if removed == 0:
        print(f"ℹ️  cache-necromancer hook 없음 — 변경 X: {sp}", file=out)
        return 0

    if new_stop:
        hooks["Stop"] = new_stop
    else:
        # Stop key 자체 제거 (빈 list 안 남기기)
        hooks.pop("Stop", None)

    _save_settings(sp, settings)
    print(f"✅ 제거 완료 ({removed}개 hook): {sp}", file=out)
    print("ℹ️  새 chat 세션부터 적용됩니다.", file=out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cn",
        description="cache-necromancer CLI (plugin marketplace 미사용 환경 fallback)",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_install = sub.add_parser("install", help="settings.json 에 Stop hook 등록")
    p_install.add_argument(
        "--force", action="store_true", help="기존 Stop hook 와 공존 강제"
    )
    sub.add_parser("uninstall", help="settings.json 에서 cn hook 제거")

    args = parser.parse_args()
    if args.cmd == "install":
        return install_main(force=args.force)
    if args.cmd == "uninstall":
        return uninstall_main()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

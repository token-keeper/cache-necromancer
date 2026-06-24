#!/usr/bin/env python3
"""cache-necromancer 설정 터미널 TUI (v0.7.0).

설계: docs/superpowers/specs/active/2026-06-24-cn-config-tui-design.md

설정 변경을 Claude 와의 LLM 대화가 아니라 터미널 번호 메뉴로 처리한다 →
LLM turn 0 + context 0. 순수 stdlib (의존성 0).

이식: SCHEMA 배열 + _resolve_root() 의 config 경로만 교체하면 다른 플러그인에
복붙으로 동작한다. 렌더/선택/라인보존 쓰기 엔진은 범용.
"""
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os  # noqa: E402

from lib.config import ensure_config_file, parse_config_file  # noqa: E402

# 노출 설정 항목 (이식 시 이 배열만 교체). section/key 는 config.toml 좌표.
# grace_seconds 는 advanced 라 제외 — 직접 편집 안내.
SCHEMA: list[dict] = [
    {
        "section": "wake", "key": "arm", "label": "소생 방식",
        "type": "choice", "default": "manual",
        "options": [
            ("manual", "/cn:set 충전분만 소생, 알림은 계속"),
            ("always", "매 turn 자동 arm — 깜빡 보호, wake 비용 발생"),
        ],
    },
    {
        "section": "notify", "key": "enabled", "label": "만료 임박 macOS 알림",
        "type": "bool", "default": True,
        "options": [("true", "알림 켬"), ("false", "알림 끔")],
    },
    {
        "section": "general", "key": "refresh_interval_minutes",
        "label": "갱신 sleep(분) — TTL 만료 직전까지 대기",
        "type": "int", "default": 50,
        "options": [("2", "테스트"), ("30", "빠름"), ("50", "기본"), ("90", "느림")],
    },
    {
        "section": "general", "key": "max_refresh_count",
        "label": "wake 상한 (always 연쇄 / set 1회 충전 상한)",
        "type": "int", "default": 10,
        "options": [("5", "보수"), ("10", "기본"), ("20", "여유"), ("50", "거의무제한")],
    },
    {
        "section": "display", "key": "recap_style", "label": "만료 표시 방식",
        "type": "choice", "default": "compact",
        "options": [("box", "박스로 크게"), ("compact", "한 줄")],
    },
    {
        "section": "general", "key": "language", "label": "메시지 언어",
        "type": "str", "default": "en",
        "options": [("en", "English"), ("ko", "한국어"), ("ja", "日本語"), ("zh", "中文")],
    },
    {
        "section": "general", "key": "cache_ttl_minutes",
        "label": "캐시 수명(분) — recap 만료시각 계산 기준",
        "type": "int", "default": 60,
        "options": [("60", "기본(1h)"), ("5", "테스트")],
    },
]


def current_value(data: dict, item: dict):
    """raw TOML dict 에서 항목 현재값. 없으면 항목 default."""
    return data.get(item["section"], {}).get(item["key"], item["default"])


def format_value(raw: str, vtype: str) -> str:
    """사용자 입력 `raw` 를 `vtype` 에 맞는 TOML literal 로 변환.

    - bool → `true`/`false` (따옴표 없음)
    - int  → 정수 문자열 (검증; 비정수면 ValueError)
    - choice/str → `"..."` (따옴표)
    """
    if vtype == "bool":
        return "true" if str(raw).strip().lower() in ("true", "1", "yes", "on") else "false"
    if vtype == "int":
        return str(int(str(raw).strip()))
    return f'"{str(raw).strip()}"'


def update_toml_text(text: str, section: str, key: str, literal: str) -> str:
    """TOML `text` 의 `[section]` 안 `key` 값을 `literal` 로 교체(주석 보존).

    literal 은 이미 TOML 포맷된 값 (예: `"always"`, `true`, `50`).
    키가 없으면 섹션 끝에 추가, 섹션도 없으면 텍스트 끝에 섹션+키 추가.
    """
    line_re = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s*#.*)?$")
    lines = text.splitlines(keepends=True)
    sec_start: int | None = None
    sec_end = len(lines)
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section:  # 다음 섹션 헤더 → 현재 섹션 본문 끝
                sec_end = i
                break
            if stripped[1:-1].strip() == section:
                in_section = True
                sec_start = i
            continue
        if in_section:
            m = line_re.match(line.rstrip("\n"))
            if m:
                nl = "\n" if line.endswith("\n") else ""
                comment = m.group(3) or ""
                lines[i] = f"{m.group(1)}{literal}{comment}{nl}"
                return "".join(lines)

    new_line = f"{key} = {literal}\n"
    if sec_start is not None:  # 섹션은 있고 키만 없음 → 섹션 본문 끝에 삽입
        insert_at = sec_end
        while insert_at > sec_start + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        lines.insert(insert_at, new_line)
        return "".join(lines)
    # 섹션 자체 없음 → 텍스트 끝에 섹션+키 추가
    tail = "" if (text == "" or text.endswith("\n")) else "\n"
    return f"{text}{tail}\n[{section}]\n{new_line}"


def _validate_free(item: dict, raw: str) -> "str | None":
    """자유입력(int/str) 검증. 유효하면 정규화 값, 무효면 None.

    - int: 정수이며 1 이상 (음수·0·비정수 거부 → 크래시/무의미 sleep 방지)
    - str: 개행·따옴표·제어문자 없음 (TOML 구조 파괴 방지)
    """
    if item["type"] == "int":
        try:
            n = int(raw)
        except ValueError:
            return None
        return str(n) if n >= 1 else None
    # str: TOML 문자열을 깨는 문자 차단
    if any(c in raw for c in '"\\\n\r\t') or "'" in raw:
        return None
    return raw


def _matches_current(opt_val: str, current) -> bool:
    """옵션값 문자열이 현재값과 같은가 (bool 은 true/false 문자열로 비교)."""
    if isinstance(current, bool):
        return opt_val == ("true" if current else "false")
    return str(opt_val) == str(current)


def prompt_item(item: dict, current, input_fn=input) -> "str | None":
    """한 항목의 번호 메뉴 출력 + 입력 1회. 선택값(str) 또는 None(유지).

    - 빈 입력(Enter) → None (현재값 유지)
    - 유효 번호 → 해당 옵션 값
    - int/str 타입은 옵션 밖 값을 직접 입력 가능
    - 잘못된 입력(범위 밖 번호 등, 자유입력 불가 타입) → None (유지)
    """
    options = item["options"]
    allow_free = item["type"] in ("int", "str")
    print(f"\n{item['label']}")
    for i, (val, desc) in enumerate(options, 1):
        mark = "  ✓ (현재)" if _matches_current(val, current) else ""
        print(f"   {i}) {val}{mark}   {desc}")
    hint = ", 또는 직접 입력" if allow_free else ""
    raw = input_fn(f"   선택 (Enter=유지{hint}): ").strip()
    if raw == "":
        return None
    if raw.isdecimal():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    # 옵션 번호 아님 → 자유입력(int/str) 검증
    if allow_free:
        valid = _validate_free(item, raw)
        if valid is None:
            print("   ⚠️  유효하지 않은 입력 — 현재값 유지")
        return valid
    return None


def apply_changes(path: Path, changes: list) -> bool:
    """변경 목록 `[(item, raw_value), ...]` 을 config.toml 에 라인보존 저장.

    파일이 없으면 기본 템플릿 생성 후 적용 (다른 키·주석·사용자 편집 보존).
    IO 실패 시 traceback 대신 경고 출력 + False (cn_set._save_or_fail 와 일관).
    """
    try:
        ensure_config_file(path)
        text = path.read_text(encoding="utf-8")
        for item, raw in changes:
            literal = format_value(raw, item["type"])
            text = update_toml_text(text, item["section"], item["key"], literal)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"⚠️  저장 실패: {type(e).__name__}: {e}")
        return False
    return True


def run_tui(path: Path, input_fn=input) -> list:
    """전체 항목 순회 → 변경분 수집 → 저장 → 요약. 변경 목록 반환.

    현재값과 같은 선택은 변경으로 치지 않는다. 변경 0 이면 파일도 안 건드림.
    """
    data, _ = parse_config_file(path)
    print("╭─ cache-necromancer 설정 ─────────────────╮")
    changes: list = []
    for item in SCHEMA:
        cur = current_value(data, item)
        chosen = prompt_item(item, cur, input_fn)
        if chosen is not None and not _matches_current(chosen, cur):
            changes.append((item, chosen))
    print("╰──────────────────────────────────────────╯")
    if not changes:
        print("변경 사항 없음.")
        return changes
    if not apply_changes(path, changes):
        return changes  # 실패 경고는 apply_changes 가 출력
    for item, raw in changes:
        print(f"✓ {item['section']}.{item['key']} → {raw}")
    print("저장됨 → 다음 Stop hook 발화부터 자동 적용. 재시작 불필요.")
    return changes


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _print_hint() -> None:
    """`/cn:config` hook 이 부르는 런처 안내 (turn 0 · context 0)."""
    script = Path(__file__).resolve()
    print("⚙️  설정 변경은 새 터미널에서 아래를 실행하세요 (turn 0 · context 0):")
    print(f'   python3 "{script}"')
    print("   (인터랙티브 번호 메뉴 — Claude 대화를 거치지 않아 맥락을 소비하지 않음)")


def main(argv: "list[str] | None" = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "--hint":
        _print_hint()
        return 0
    path = _resolve_root() / "config.toml"
    try:
        run_tui(path)
    except (EOFError, KeyboardInterrupt):
        print("\n취소됨 (변경 없음).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

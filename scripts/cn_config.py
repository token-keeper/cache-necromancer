#!/usr/bin/env python3
"""cache-necromancer 설정 터미널 메뉴 (v0.12.0).

설계: docs/superpowers/specs/completed/2026/Q2/2026-06-24-cn-config-tui-design.md

설정 변경을 Claude 와의 LLM 대화가 아니라 터미널 번호 메뉴로 처리한다 →
LLM turn 0 + context 0. 순수 stdlib (의존성 0).

v0.12.0: 현재값은 실제 적용값(`load_config`), 저장 시 무시되는 옛 키·옛 섹션 정리,
문구는 설정 language(ko·en·ja·zh) 기준.
v0.13.0: mod 설정 패널용 `--json`(적용 설정 + 항목) · `--set section.key=value`, 저장은 원자적.
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os  # noqa: E402

from lib.config import (  # noqa: E402
    OBSOLETE_KEYS,
    Config,
    detect_obsolete_keys,
    ensure_config_file,
    load_config,
    parse_config_file,
)

# 노출 설정 항목. section/key 는 config.toml 좌표, 문구는 _TEXT[lang]["items"][key].
# cache_ttl_minutes 는 메뉴에 없다 (interval 이상으로 줄이면 깨우기가 꺼짐) — 파일 직접 편집.
SCHEMA: list[dict] = [
    {"section": "general", "key": "auto_wakes", "type": "int", "min": 0, "max": 10,
     "options": ["0", "1", "2", "3"]},
    {"section": "general", "key": "refresh_interval_minutes", "type": "int", "min": 1,
     "options": ["30", "45", "50"]},
    {"section": "display", "key": "countdown", "type": "bool",
     "options": ["true", "false"]},
    {"section": "general", "key": "language", "type": "choice",
     "options": ["en", "ko", "ja", "zh"]},
]

_LANG_NAMES = ["English", "한국어", "日本語", "中文"]

_TEXT: dict[str, dict] = {
    "ko": {
        "items": {
            "auto_wakes": ("자동 깨우기 — 자리비움마다 최대 횟수",
                           ["끔 (띠·토스트만)", "적게", "기본", "여유"]),
            "refresh_interval_minutes": ("깨우기 시점(분) — 캐시 마지막 적중 뒤",
                                         ["이르게", "조금 이르게", "기본 (만료 10분 전)"]),
            "countdown": ("입력창 아래 캐시 카운트다운 띠", ["표시", "숨김"]),
            "language": ("메시지 언어", _LANG_NAMES),
        },
        "title": "cache-necromancer 설정",
        "file_note": "그 밖의 값(cache_ttl_minutes 등)은 파일 직접 편집: {path}",
        "current": "(현재)",
        "select": "선택 (Enter=유지{free}): ",
        "free": ", 또는 직접 입력",
        "invalid": "유효하지 않은 입력 — 현재값 유지",
        "no_change": "변경 사항 없음.",
        "save_failed": "저장 실패: {err}",
        "cleaned": "무시되던 옛 설정 {n}줄 정리",
        "cleanup_skipped": "옛 설정 정리는 건너뜀 (정리하면 파일이 깨짐 — 직접 편집하세요)",
        "save_cancelled": "저장 취소 — 결과가 올바른 TOML 이 아님 (파일 문법을 확인하세요)",
        "saved": "저장됨 · 열린 세션 모두에 바로 반영",
        "bad_key": "알 수 없는 설정: {id} (가능: {allowed})",
        "bad_value": "잘못된 값: {id}={value} (가능: {allowed})",
        "interval_ge_ttl": "깨우기 시점은 캐시 수명 {ttl}분보다 짧아야 함: {value}",
        "hint": "설정 변경은 새 터미널에서 아래를 실행하세요 (turn 0 · context 0):",
        "hint_note": "(번호 메뉴 — Claude 대화를 거치지 않아 맥락을 소비하지 않음)",
        "cancelled": "취소됨 (변경 없음).",
    },
    "en": {
        "items": {
            "auto_wakes": ("Auto wakes — max per time away",
                           ["off (band and toasts only)", "fewer", "default", "more"]),
            "refresh_interval_minutes": ("Wake timing (min) — after the last cache hit",
                                         ["early", "a bit early", "default (10 min before expiry)"]),
            "countdown": ("Cache countdown band below the prompt", ["show", "hide"]),
            "language": ("Message language", _LANG_NAMES),
        },
        "title": "cache-necromancer settings",
        "file_note": "Other values (cache_ttl_minutes etc.): edit the file directly: {path}",
        "current": "(current)",
        "select": "Choose (Enter=keep{free}): ",
        "free": ", or type a value",
        "invalid": "Invalid input — keeping the current value",
        "no_change": "No changes.",
        "save_failed": "Save failed: {err}",
        "cleaned": "Removed {n} old ignored setting line(s)",
        "cleanup_skipped": "Skipped removing old settings (it would break the file — edit it by hand)",
        "save_cancelled": "Save cancelled — the result is not valid TOML (check the file syntax)",
        "saved": "Saved · applies to every open session right away",
        "bad_key": "Unknown setting: {id} (allowed: {allowed})",
        "bad_value": "Invalid value: {id}={value} (allowed: {allowed})",
        "interval_ge_ttl": "Wake timing must be shorter than the cache TTL of {ttl} min: {value}",
        "hint": "To change settings, run this in a new terminal (turn 0 · context 0):",
        "hint_note": "(numbered menu — runs outside the Claude chat, so it uses no context)",
        "cancelled": "Cancelled (no changes).",
    },
    "ja": {
        "items": {
            "auto_wakes": ("自動延長 — 離席ごとの最大回数",
                           ["オフ (帯・トーストのみ)", "少なめ", "既定", "多め"]),
            "refresh_interval_minutes": ("延長タイミング(分) — キャッシュ最終ヒット後",
                                         ["早め", "やや早め", "既定 (期限切れ10分前)"]),
            "countdown": ("入力欄下のキャッシュカウントダウン帯", ["表示", "非表示"]),
            "language": ("メッセージ言語", _LANG_NAMES),
        },
        "title": "cache-necromancer 設定",
        "file_note": "その他の値 (cache_ttl_minutes など) はファイルを直接編集: {path}",
        "current": "(現在)",
        "select": "選択 (Enter=維持{free}): ",
        "free": "、または直接入力",
        "invalid": "無効な入力 — 現在の値を維持",
        "no_change": "変更なし。",
        "save_failed": "保存失敗: {err}",
        "cleaned": "無視されていた古い設定 {n} 行を整理",
        "cleanup_skipped": "古い設定の整理はスキップ (整理するとファイルが壊れるため — 直接編集してください)",
        "save_cancelled": "保存を中止 — 結果が正しい TOML ではありません (ファイルの文法を確認してください)",
        "saved": "保存しました · 開いているすべてのセッションにすぐ反映",
        "bad_key": "不明な設定: {id} (指定可能: {allowed})",
        "bad_value": "無効な値: {id}={value} (指定可能: {allowed})",
        "interval_ge_ttl": "延長タイミングはキャッシュ寿命 {ttl}分より短くしてください: {value}",
        "hint": "設定の変更は新しいターミナルで次を実行してください (turn 0 · context 0):",
        "hint_note": "(番号メニュー — Claude の会話を通さないのでコンテキストを消費しません)",
        "cancelled": "キャンセル (変更なし)。",
    },
    "zh": {
        "items": {
            "auto_wakes": ("自动唤醒 — 每次离开的最多次数",
                           ["关闭 (仅横条和提示)", "较少", "默认", "较多"]),
            "refresh_interval_minutes": ("唤醒时机(分钟) — 缓存最后命中之后",
                                         ["提前", "稍微提前", "默认 (过期前 10 分钟)"]),
            "countdown": ("输入框下方的缓存倒计时横条", ["显示", "隐藏"]),
            "language": ("消息语言", _LANG_NAMES),
        },
        "title": "cache-necromancer 设置",
        "file_note": "其他值 (cache_ttl_minutes 等) 请直接编辑文件: {path}",
        "current": "(当前)",
        "select": "选择 (Enter=保持{free}): ",
        "free": "，或直接输入",
        "invalid": "输入无效 — 保持当前值",
        "no_change": "没有更改。",
        "save_failed": "保存失败: {err}",
        "cleaned": "已清理 {n} 行被忽略的旧设置",
        "cleanup_skipped": "已跳过清理旧设置 (清理会损坏文件 — 请手动编辑)",
        "save_cancelled": "已取消保存 — 结果不是有效的 TOML (请检查文件语法)",
        "saved": "已保存 · 立即应用到所有打开的会话",
        "bad_key": "未知设置: {id} (可用: {allowed})",
        "bad_value": "无效值: {id}={value} (可用: {allowed})",
        "interval_ge_ttl": "唤醒时机必须短于缓存寿命 {ttl} 分钟: {value}",
        "hint": "要更改设置，请在新终端中运行以下命令 (turn 0 · context 0):",
        "hint_note": "(编号菜单 — 不经过 Claude 对话，不消耗上下文)",
        "cancelled": "已取消 (没有更改)。",
    },
}


def _lang(cfg: Config) -> str:
    return cfg.language if cfg.language in _TEXT else "en"


def current_value(cfg: Config, item: dict):
    """실제 적용 설정(`load_config` 결과)에서 항목 현재값."""
    obj = cfg if item["section"] == "general" else getattr(cfg, item["section"])
    return getattr(obj, item["key"])


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


def _header_name(line: str) -> "str | None":
    """섹션 헤더 줄이면 섹션 이름, 아니면 None. `[wake]  # 메모` 처럼 뒤 주석도 허용."""
    s = line.split("#", 1)[0].strip()
    if s.startswith("[") and s.endswith("]"):
        return s[1:-1].strip()
    return None


_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


def _is_obsolete(section: str, key: str) -> bool:
    return f"{section}.{key}" in OBSOLETE_KEYS or f"{section}.*" in OBSOLETE_KEYS


def remove_obsolete_keys(text: str) -> "tuple[str, int]":
    """`OBSOLETE_KEYS` 에 해당하는 키 줄을 지우고, 키가 하나도 안 남은 옛 섹션
    (`section.*` 전체가 옛 키인 섹션) 헤더도 지운다. 주석·빈 줄은 남긴다.
    (결과 텍스트, 지운 키 줄 수) 반환.

    ponytail: 한 줄짜리 `key = value` 만 인식 — 여러 줄 값은 첫 줄만 지워져 TOML 이
    깨질 수 있다. apply_changes 가 결과를 tomllib 로 검증해 그때는 정리를 건너뛴다.
    """
    removed = 0
    out: list = []
    section = ""
    header_at: "int | None" = None  # 지울 수도 있는 옛 섹션 헤더의 out 위치
    has_key = False

    def drop_empty_header() -> None:
        if header_at is not None and not has_key:
            out[header_at] = None

    for line in text.splitlines(keepends=True):
        name = _header_name(line)
        if name is not None:
            drop_empty_header()
            section, has_key = name, False
            header_at = len(out) if f"{name}.*" in OBSOLETE_KEYS else None
            out.append(line)
            continue
        m = _KEY_RE.match(line)
        if m:
            if _is_obsolete(section, m.group(1)):
                removed += 1
                continue
            has_key = True
        out.append(line)
    drop_empty_header()
    return "".join(x for x in out if x is not None), removed


def update_toml_text(text: str, section: str, key: str, literal: str) -> str:
    """TOML `text` 의 `[section]` 안 `key` 값을 `literal` 로 교체(주석 보존).

    literal 은 이미 TOML 포맷된 값 (예: `"ko"`, `true`, `50`).
    키가 없으면 섹션 끝에 추가, 섹션도 없으면 텍스트 끝에 섹션+키 추가.
    """
    line_re = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s*#.*)?$")
    lines = text.splitlines(keepends=True)
    sec_start: int | None = None
    sec_end = len(lines)
    in_section = False
    for i, line in enumerate(lines):
        name = _header_name(line)
        if name is not None:
            if in_section:  # 다음 섹션 헤더 → 현재 섹션 본문 끝
                sec_end = i
                break
            if name == section:
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
    """int 항목 직접 입력 검증. 정수이며 항목의 min~max 범위면 정규화 값, 아니면 None."""
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < item.get("min", 1) or ("max" in item and n > item["max"]):
        return None
    return str(n)


def _matches_current(opt_val: str, current) -> bool:
    """옵션값 문자열이 현재값과 같은가 (bool 은 true/false 문자열로 비교)."""
    if isinstance(current, bool):
        return opt_val == ("true" if current else "false")
    return str(opt_val) == str(current)


def prompt_item(item: dict, current, input_fn=input, lang: str = "en") -> "str | None":
    """한 항목의 번호 메뉴 출력 + 입력 1회. 선택값(str) 또는 None(유지).

    - 빈 입력(Enter) → None (현재값 유지)
    - 유효 번호 → 해당 옵션 값
    - int 타입은 옵션 밖 값을 직접 입력 가능
    - 잘못된 입력(범위 밖 번호 등, 자유입력 불가 타입) → None (유지)
    """
    t = _TEXT[lang]
    label, descs = t["items"][item["key"]]
    options = item["options"]
    allow_free = item["type"] == "int"
    print(f"\n{label}")
    for i, (val, desc) in enumerate(zip(options, descs), 1):
        mark = f"  ✓ {t['current']}" if _matches_current(val, current) else ""
        print(f"   {i}) {val}{mark}   {desc}")
    raw = input_fn("   " + t["select"].format(free=t["free"] if allow_free else "")).strip()
    if raw == "":
        return None
    if raw.isdecimal():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    # 옵션 번호 아님 → int 직접 입력 검증
    if allow_free:
        valid = _validate_free(item, raw)
        if valid is None:
            print(f"   ⚠️  {t['invalid']}")
        return valid
    return None


def _with_changes(text: str, changes: list) -> str:
    for item, raw in changes:
        text = update_toml_text(text, item["section"], item["key"], format_value(raw, item["type"]))
    return text


def _is_valid_toml(text: str) -> bool:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True


def _atomic_write(path: Path, text: str) -> None:
    """같은 디렉터리 임시 파일(mkstemp = 0o600) → `os.replace`. 다른 세션이 반쯤 쓴 파일을 읽지 않게.

    심링크면 링크 대상 파일을 바꾼다 (링크를 일반 파일로 바꾸지 않게).
    """
    path = path.resolve()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_changes(path: Path, changes: list, lang: str = "en", out=None) -> "int | None":
    """변경 목록 `[(item, raw_value), ...]` 을 config.toml 에 라인보존 저장.

    파일이 없으면 기본 템플릿 생성 후 적용 (다른 키·주석·사용자 편집 보존).
    무시되는 옛 키(`OBSOLETE_KEYS`) 줄과 비게 된 옛 섹션 헤더도 지운다.
    쓰기 전에 결과를 tomllib 로 검증: 정리 때문에 깨지면 정리 없이 값 변경만,
    그래도 깨지면 저장하지 않는다.
    저장은 원자적(`_atomic_write`), 권한 0o600. 안내 문구는 `out`(기본 stdout)으로.
    반환: 지운 옛 키 줄 수, 저장 안 함(검증 실패·IO 실패·UTF-8 아님)이면 None.
    """
    t = _TEXT[lang]
    out = out if out is not None else sys.stdout
    try:
        ensure_config_file(path)
        original = path.read_text(encoding="utf-8")
        cleaned, removed = remove_obsolete_keys(original)
        text = _with_changes(cleaned, changes)
        if not _is_valid_toml(text):
            removed = 0
            text = _with_changes(original, changes)
            if not _is_valid_toml(text):
                print("⚠️  " + t["save_cancelled"], file=out)
                return None
            print("⚠️  " + t["cleanup_skipped"], file=out)
        _atomic_write(path, text)
    except (OSError, UnicodeDecodeError) as e:  # UTF-8 아닌 파일도 traceback 대신 저장 취소
        print("⚠️  " + t["save_failed"].format(err=f"{type(e).__name__}: {e}"), file=out)
        return None
    return removed


def run_tui(path: Path, input_fn=input) -> list:
    """전체 항목 순회 → 변경분 수집 → 저장 → 요약. 변경 목록 반환.

    현재값(실제 적용값)과 같은 선택은 변경으로 치지 않는다. 값 변경이 없어도
    무시되는 옛 키가 있으면 그것만 정리해 저장한다. 둘 다 없으면 파일을 안 건드림.
    """
    cfg = load_config(path)
    lang = _lang(cfg)
    t = _TEXT[lang]
    has_obsolete = bool(detect_obsolete_keys(parse_config_file(path)[0]))
    print(f"╭─ {t['title']} ─────────────────╮")
    print("  " + t["file_note"].format(path=path))
    changes: list = []
    for item in SCHEMA:
        cur = current_value(cfg, item)
        chosen = prompt_item(item, cur, input_fn, lang)
        if (chosen is not None and item["key"] == "refresh_interval_minutes"
                and int(chosen) >= cfg.cache_ttl_minutes):  # --set 과 같은 검사 — 깨우기가 꺼지는 함정
            print("   ⚠️  " + t["interval_ge_ttl"].format(ttl=cfg.cache_ttl_minutes, value=chosen))
            chosen = None
        if chosen is not None and not _matches_current(chosen, cur):
            changes.append((item, chosen))
    print("╰──────────────────────────────────────────╯")
    if not changes and not has_obsolete:
        print(t["no_change"])
        return changes
    removed = apply_changes(path, changes, lang)
    if removed is None:
        return changes  # 실패 안내는 apply_changes 가 출력
    for item, raw in changes:
        print(f"✓ {item['section']}.{item['key']} → {raw}")
    if removed:
        print("✓ " + t["cleaned"].format(n=removed))
    if changes:
        print(t["saved"])
    elif not removed:
        print(t["no_change"])
    return changes


def _resolve_root() -> Path:
    root = os.environ.get("CN_ROOT")
    return Path(root) if root else Path.home() / ".cache-necromancer"


def _print_hint() -> None:
    """`/cn:config` hook 이 부르는 런처 안내 (turn 0 · context 0)."""
    t = _TEXT[_lang(load_config(_resolve_root() / "config.toml"))]
    script = Path(__file__).resolve()
    print("⚙️  " + t["hint"])
    print(f'   python3 "{script}"')
    print("   " + t["hint_note"])


def _item_id(item: dict) -> str:
    return f"{item['section']}.{item['key']}"


def _as_option(value) -> str:
    """현재값을 옵션값 문자열로 (bool 은 "true"/"false")."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def config_json(path: Path) -> dict:
    """`--json` 출력 — 적용 설정(mod `CacheNecromancerConfig` 모양) + 패널 항목. 파일은 안 건드린다."""
    cfg = load_config(path)
    t = _TEXT[_lang(cfg)]
    items = []
    for item in SCHEMA:
        label, descs = t["items"][item["key"]]
        items.append({
            "id": _item_id(item),
            "label": label,
            "current": _as_option(current_value(cfg, item)),
            "options": [{"value": v, "text": f"{v} · {d}"} for v, d in zip(item["options"], descs)],
        })
    return {
        "config": {
            "ttlMinutes": cfg.cache_ttl_minutes,
            "warnAfterMinutes": cfg.refresh_interval_minutes,
            "autoWakes": cfg.auto_wakes,
            "countdown": cfg.display.countdown,
            "language": cfg.language,
        },
        "items": items,
    }


def _allowed(item: dict) -> str:
    if item["type"] == "int":
        return f"{item['min']}~{item['max']}" if "max" in item else f"{item['min']}+"
    return "|".join(item["options"])


def _check_set(arg: str, cfg: Config, t: dict) -> "tuple[dict, str]":
    """`section.key=value` 하나 검증. (item, 정규화 값) 반환, 잘못되면 ValueError(사유 1줄)."""
    by_id = {_item_id(i): i for i in SCHEMA}
    key, sep, raw = arg.partition("=")
    item = by_id.get(key.strip())
    if not sep or item is None:
        raise ValueError(t["bad_key"].format(id=key.strip(), allowed=", ".join(by_id)))
    raw = raw.strip()
    bad = ValueError(t["bad_value"].format(id=key.strip(), value=raw, allowed=_allowed(item)))
    if item["type"] == "int":
        value = _validate_free(item, raw) if raw.isdecimal() else None
        if value is None:
            raise bad
        if item["key"] == "refresh_interval_minutes" and int(value) >= cfg.cache_ttl_minutes:
            raise ValueError(t["interval_ge_ttl"].format(ttl=cfg.cache_ttl_minutes, value=value))
        return item, value
    if raw not in item["options"]:  # bool 은 options = ["true", "false"]
        raise bad
    return item, raw


def set_values(path: Path, args: list) -> int:
    """`--set section.key=value ...` — 검증 후 원자 저장. 성공 stdout 1줄·exit 0, 실패 stderr 1줄·exit 1.

    파일의 다른 잘못된 값 경고(`[cn:warn]`)는 버린다 — 패널은 stderr 첫 줄을 실패 사유로 보인다.
    """
    with contextlib.redirect_stderr(io.StringIO()):
        cfg = load_config(path)
    t = _TEXT[_lang(cfg)]
    try:
        if not args:
            raise ValueError(t["bad_key"].format(id="", allowed=", ".join(_item_id(i) for i in SCHEMA)))
        changes = [_check_set(a, cfg, t) for a in args]
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    buf = io.StringIO()
    if apply_changes(path, changes, _lang(cfg), out=buf) is None:
        print(buf.getvalue().strip().removeprefix("⚠️  ").replace("\n", " "), file=sys.stderr)
        return 1
    print(t["saved"])
    return 0


def main(argv: "list[str] | None" = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "--hint":
        _print_hint()
        return 0
    if argv and argv[0] == "--json":
        print(json.dumps(config_json(_resolve_root() / "config.toml"), ensure_ascii=False))
        return 0
    if argv and argv[0] == "--set":
        return set_values(_resolve_root() / "config.toml", argv[1:])
    path = _resolve_root() / "config.toml"
    try:
        run_tui(path)
    except (EOFError, KeyboardInterrupt):
        print("\n" + _TEXT[_lang(load_config(path))]["cancelled"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

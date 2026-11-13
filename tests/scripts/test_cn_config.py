"""cn_config.py — 터미널 설정 메뉴 (v0.12.0).

순수 함수(라인보존 쓰기·옛 키 정리·값 포맷·현재값 추출) 중심 테스트.
메뉴 루프는 input_fn 주입으로 검증.
"""
import sys
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.config import Config, load_config  # noqa: E402
from scripts.cn_config import (  # noqa: E402
    SCHEMA,
    _TEXT,
    apply_changes,
    current_value,
    format_value,
    main,
    prompt_item,
    remove_obsolete_keys,
    run_tui,
    update_toml_text,
)

_ITEM = {i["key"]: i for i in SCHEMA}
_AUTO = _ITEM["auto_wakes"]
_INTERVAL = _ITEM["refresh_interval_minutes"]
_COUNTDOWN = _ITEM["countdown"]
_LANG = _ITEM["language"]
_KEEP_ALL = ["", "", "", ""]  # SCHEMA 4개 항목 전부 Enter


def _inputs(*values):
    it = iter(values)
    return lambda _: next(it)


# ── SCHEMA ──────────────────────────────────────────────


def test_schema_covers_user_keys():
    keys = {(i["section"], i["key"]) for i in SCHEMA}
    assert keys == {
        ("general", "auto_wakes"),
        ("general", "refresh_interval_minutes"),
        ("display", "countdown"),
        ("general", "language"),
    }


def test_schema_presets():
    assert _AUTO["options"] == ["0", "1", "2", "3"]
    assert _INTERVAL["options"] == ["30", "45", "50"]  # 2·90 프리셋 삭제
    assert _LANG["options"] == ["en", "ko", "ja", "zh"]


def test_every_language_has_text_for_every_item():
    for lang, t in _TEXT.items():
        for item in SCHEMA:
            label, descs = t["items"][item["key"]]
            assert label
            assert len(descs) == len(item["options"]), (lang, item["key"])


# ── 현재값 = 실제 적용값 ───────────────────────────────────


def test_current_value_from_config_defaults():
    cfg = Config()
    assert current_value(cfg, _AUTO) == 2
    assert current_value(cfg, _INTERVAL) == 50
    assert current_value(cfg, _COUNTDOWN) is True
    assert current_value(cfg, _LANG) == "en"


def test_current_value_reads_loaded_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[general]\nauto_wakes = 0\nlanguage = "ko"\n\n[display]\ncountdown = false\n')
    cfg = load_config(path)
    assert current_value(cfg, _AUTO) == 0
    assert current_value(cfg, _LANG) == "ko"
    assert current_value(cfg, _COUNTDOWN) is False


def test_run_tui_marks_effective_value_not_raw(tmp_path, capsys):
    """옛 max_refresh_count = 10 은 무시되고 실제 적용값 auto_wakes=2 가 현재로 표시된다."""
    path = tmp_path / "config.toml"
    path.write_text('[general]\nmax_refresh_count = 10\n')
    run_tui(path, input_fn=_inputs(*_KEEP_ALL))
    out = capsys.readouterr().out
    assert "3) 2  ✓" in out  # auto_wakes 옵션 3번(값 2)이 현재


# ── 헤더·키 쓰기 ──────────────────────────────────────────


def test_update_replaces_value_preserving_comment():
    text = "[general]\nauto_wakes = 2        # 자리비움마다\n"
    out = update_toml_text(text, "general", "auto_wakes", "3")
    assert "auto_wakes = 3        # 자리비움마다" in out


def test_update_targets_correct_section_and_preserves_others():
    text = '[general]\nlanguage = "en"\n\n[display]\ncountdown = true\n'
    out = update_toml_text(text, "display", "countdown", "false")
    assert "countdown = false" in out
    assert 'language = "en"' in out


def test_update_adds_key_when_missing_in_section():
    text = '[general]\nlanguage = "en"\n'
    out = update_toml_text(text, "general", "auto_wakes", "1")
    assert 'language = "en"' in out
    assert "auto_wakes = 1" in out


def test_update_appends_section_when_missing():
    text = '[general]\nlanguage = "en"\n'
    out = update_toml_text(text, "display", "countdown", "false")
    assert "[display]\ncountdown = false" in out
    assert 'language = "en"' in out


def test_update_recognizes_header_with_comment():
    """`[display]  # 메모` 도 헤더 — 섹션을 끝에 하나 더 만들면 TOML 이 깨진다."""
    text = "[display]  # 표시\ncountdown = true\n"
    out = update_toml_text(text, "display", "countdown", "false")
    assert out.count("[display]") == 1
    assert "countdown = false" in out
    tomllib.loads(out)  # 중복 섹션 없음


def test_update_adds_key_into_commented_header_section():
    text = '[general]   # 일반\nlanguage = "en"\n'
    out = update_toml_text(text, "general", "auto_wakes", "3")
    assert out.count("[general]") == 1
    assert tomllib.loads(out)["general"]["auto_wakes"] == 3


# ── 옛 키 정리 ─────────────────────────────────────────────

_LEGACY_FILE = """\
# cache-necromancer 설정 (v0.1) — 수정 후 데몬 재시작 필요
[general]
mode = "hybrid"
refresh_interval_minutes = 45
max_refresh_count = 10
language = "ko"

[notify]
# 알림 메모
enabled = true
system_notification = false

[wake]   # 정책
arm = "always"
grace_seconds = 60

[refresh]
hybrid_wait_seconds = 30

[advanced]
foo = 1

[display]
recap_style = "box"
countdown = false
"""


def test_remove_obsolete_keys_drops_keys_and_empty_old_sections():
    out, removed = remove_obsolete_keys(_LEGACY_FILE)
    assert removed == 9
    data = tomllib.loads(out)
    assert data == {
        "general": {"refresh_interval_minutes": 45, "language": "ko"},
        "display": {"countdown": False},
    }
    for header in ("[notify]", "[wake]", "[refresh]", "[advanced]"):
        assert header not in out
    # 주석 줄은 남김
    assert "# 알림 메모" in out
    assert "# cache-necromancer 설정 (v0.1)" in out


def test_remove_obsolete_keys_keeps_new_file_unchanged():
    text = '[general]\nauto_wakes = 2\nlanguage = "en"\n\n[display]\ncountdown = true\n'
    assert remove_obsolete_keys(text) == (text, 0)


def test_apply_changes_cleans_obsolete_keys(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(_LEGACY_FILE)
    assert apply_changes(path, [(_AUTO, "1")]) == 9  # 지운 옛 키 줄 수
    data = tomllib.loads(path.read_text())
    assert data["general"] == {"refresh_interval_minutes": 45, "language": "ko", "auto_wakes": 1}
    assert set(data) == {"general", "display"}


def test_run_tui_cleans_obsolete_even_without_value_change(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[wake]\narm = "always"\n\n[general]\nlanguage = "en"\n')
    changes = run_tui(path, input_fn=_inputs(*_KEEP_ALL))
    assert changes == []
    assert tomllib.loads(path.read_text()) == {"general": {"language": "en"}}
    assert "Removed 1 old ignored setting line" in capsys.readouterr().out


_MULTILINE_STR = '[general]\nlanguage = "en"\n\n[refresh]\nprompt = """\nkeep alive\n"""\n'
_MULTILINE_ARRAY = '[general]\nlanguage = "en"\n\n[advanced]\nitems = [\n  "a",\n  "b",\n]\n'


@pytest.mark.parametrize("text", [_MULTILINE_STR, _MULTILINE_ARRAY])
def test_apply_changes_skips_cleanup_when_it_would_break_toml(tmp_path, capsys, text):
    """여러 줄 값은 첫 줄만 지워져 TOML 이 깨진다 → 정리 없이 값 변경만 저장."""
    path = tmp_path / "config.toml"
    path.write_text(text)
    assert apply_changes(path, [(_AUTO, "1")]) == 0
    data = tomllib.loads(path.read_text())  # 파일이 깨지지 않음
    assert data["general"]["auto_wakes"] == 1
    assert "Skipped removing old settings" in capsys.readouterr().out


@pytest.mark.parametrize("text", [_MULTILINE_STR, _MULTILINE_ARRAY])
def test_run_tui_without_changes_keeps_multiline_file_intact(tmp_path, capsys, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    assert run_tui(path, input_fn=_inputs(*_KEEP_ALL)) == []
    assert path.read_text() == text
    out = capsys.readouterr().out
    assert "Removed" not in out  # 실제로 지운 줄이 없으면 정리 안내도 없음


def test_apply_changes_cancels_save_when_file_already_broken(tmp_path, capsys):
    path = tmp_path / "config.toml"
    broken = "[general]\nlanguage = \n"
    path.write_text(broken)
    assert apply_changes(path, [(_AUTO, "1")]) is None
    assert path.read_text() == broken  # 저장 안 함
    assert "Save cancelled" in capsys.readouterr().out


# ── 값 포맷 ───────────────────────────────────────────────


def test_format_bool_unquoted():
    assert format_value("true", "bool") == "true"
    assert format_value("false", "bool") == "false"


def test_format_int_unquoted():
    assert format_value("50", "int") == "50"


def test_format_choice_quoted():
    assert format_value("ko", "choice") == '"ko"'


def test_format_int_rejects_non_integer():
    with pytest.raises(ValueError):
        format_value("abc", "int")


# ── 메뉴 입력 ─────────────────────────────────────────────


def test_prompt_item_returns_selected_option():
    assert prompt_item(_AUTO, 2, input_fn=lambda _: "1") == "0"  # options[0] = 끔


def test_prompt_item_enter_keeps_current():
    assert prompt_item(_AUTO, 2, input_fn=lambda _: "") is None


def test_prompt_item_free_input_for_int_in_range():
    assert prompt_item(_AUTO, 2, input_fn=lambda _: "7") == "7"
    assert prompt_item(_INTERVAL, 50, input_fn=lambda _: "40") == "40"


def test_prompt_item_rejects_auto_wakes_out_of_range():
    assert prompt_item(_AUTO, 2, input_fn=lambda _: "11") is None
    assert prompt_item(_AUTO, 2, input_fn=lambda _: "-1") is None


def test_prompt_item_rejects_bad_interval():
    assert prompt_item(_INTERVAL, 50, input_fn=lambda _: "9.5") is None
    assert prompt_item(_INTERVAL, 50, input_fn=lambda _: "abc") is None
    assert prompt_item(_INTERVAL, 50, input_fn=lambda _: "0") is None


def test_prompt_item_language_is_choice_only():
    # 4개 언어 밖 값·TOML 을 깨는 입력은 직접 입력 불가 (choice)
    assert prompt_item(_LANG, "en", input_fn=lambda _: "fr") is None
    assert prompt_item(_LANG, "en", input_fn=lambda _: 'en"\narm = "always') is None
    assert prompt_item(_LANG, "en", input_fn=lambda _: "2") == "ko"


def test_prompt_item_invalid_number_on_bool_keeps_current():
    assert prompt_item(_COUNTDOWN, True, input_fn=lambda _: "9") is None


def test_prompt_item_text_follows_language(capsys):
    prompt_item(_AUTO, 2, input_fn=lambda _: "", lang="ko")
    out = capsys.readouterr().out
    assert "자동 깨우기" in out
    assert "(현재)" in out


# ── 저장 ─────────────────────────────────────────────────


def test_apply_changes_creates_file_and_writes(tmp_path):
    path = tmp_path / "config.toml"
    apply_changes(path, [(_AUTO, "3")])
    data = tomllib.loads(path.read_text())
    assert data["general"]["auto_wakes"] == 3
    assert "refresh_interval_minutes" in data["general"]  # 템플릿의 다른 키 보존


def test_apply_changes_preserves_user_edits(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[general]\ncache_ttl_minutes = 30  # 직접 편집\n\n[display]\ncountdown = true\n")
    apply_changes(path, [(_COUNTDOWN, "false")])
    text = path.read_text()
    assert "countdown = false" in text
    assert "cache_ttl_minutes = 30  # 직접 편집" in text


def test_apply_changes_returns_false_on_oserror(tmp_path):
    path = tmp_path / "config.toml"
    path.mkdir()  # 디렉터리 → read/write 불가 (IsADirectoryError ⊂ OSError)
    assert apply_changes(path, [(_AUTO, "1")]) is None


def test_apply_changes_cancels_save_on_non_utf8_file(tmp_path, capsys):
    path = tmp_path / "config.toml"
    raw = b'[general]\nlanguage = "\xff"\n'  # UTF-8 아님
    path.write_bytes(raw)
    assert apply_changes(path, [(_AUTO, "1")]) is None  # traceback 대신 None
    assert path.read_bytes() == raw  # 저장 안 함
    assert "Save failed: UnicodeDecodeError" in capsys.readouterr().out


def test_run_tui_applies_only_changed(tmp_path):
    path = tmp_path / "config.toml"
    changes = run_tui(path, input_fn=_inputs("1", "", "", ""))  # auto_wakes=0
    assert [c[0]["key"] for c in changes] == ["auto_wakes"]
    assert tomllib.loads(path.read_text())["general"]["auto_wakes"] == 0


def test_run_tui_no_change_when_all_kept(tmp_path):
    path = tmp_path / "config.toml"
    assert run_tui(path, input_fn=lambda _: "") == []
    assert not path.exists()  # 변경 없으면 파일도 안 만듦


def test_run_tui_selecting_same_value_is_not_a_change(tmp_path):
    path = tmp_path / "config.toml"
    changes = run_tui(path, input_fn=_inputs("3", "", "", ""))  # auto_wakes 기본 2 다시 선택
    assert changes == []
    assert not path.exists()


def test_run_tui_uses_config_language(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[general]\nlanguage = "ja"\n')
    run_tui(path, input_fn=_inputs(*_KEEP_ALL))
    assert "自動延長" in capsys.readouterr().out


# ── --hint ───────────────────────────────────────────────


def test_main_hint_prints_launch_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CN_ROOT", str(tmp_path))
    (tmp_path / "config.toml").write_text('[general]\nlanguage = "ko"\n')
    assert main(["--hint"]) == 0
    out = capsys.readouterr().out
    assert "cn_config.py" in out
    assert "터미널" in out


def test_main_hint_defaults_to_english(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CN_ROOT", str(tmp_path))
    main(["--hint"])
    out = capsys.readouterr().out
    assert "new terminal" in out
    assert not (tmp_path / "config.toml").exists()  # --hint 는 파일을 만들지 않음

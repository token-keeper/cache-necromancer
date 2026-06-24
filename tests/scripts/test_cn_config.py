"""cn_config.py — 터미널 TUI 설정 (v0.7.0).

순수 함수(라인보존 쓰기·값 포맷·현재값 추출) 중심 테스트.
TUI 루프는 stdin monkeypatch 로 검증.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.cn_config import (  # noqa: E402
    SCHEMA,
    apply_changes,
    current_value,
    format_value,
    main,
    prompt_item,
    run_tui,
    update_toml_text,
)

_ARM = next(i for i in SCHEMA if i["key"] == "arm")
_RECAP = next(i for i in SCHEMA if i["key"] == "recap_style")


def test_update_replaces_value_preserving_comment():
    text = '[wake]\narm = "manual"        # 소생 방식\n'
    out = update_toml_text(text, "wake", "arm", '"always"')
    assert 'arm = "always"' in out
    assert "# 소생 방식" in out


def test_update_targets_correct_section_and_preserves_others():
    text = '[general]\nlanguage = "en"\n\n[notify]\nenabled = true\n'
    out = update_toml_text(text, "notify", "enabled", "false")
    assert "enabled = false" in out
    assert 'language = "en"' in out  # 다른 섹션 보존


def test_update_adds_key_when_missing_in_section():
    text = '[wake]\narm = "manual"\n'
    out = update_toml_text(text, "wake", "grace_seconds", "60")
    assert 'arm = "manual"' in out
    assert "grace_seconds = 60" in out


def test_update_appends_section_when_missing():
    # 구버전 파일엔 [display] 섹션이 아예 없을 수 있음
    text = '[general]\nlanguage = "en"\n'
    out = update_toml_text(text, "display", "recap_style", '"box"')
    assert "[display]" in out
    assert 'recap_style = "box"' in out
    assert 'language = "en"' in out


def test_format_bool_unquoted():
    assert format_value("true", "bool") == "true"
    assert format_value("false", "bool") == "false"


def test_format_int_unquoted():
    assert format_value("50", "int") == "50"


def test_format_choice_and_str_quoted():
    assert format_value("manual", "choice") == '"manual"'
    assert format_value("ko", "str") == '"ko"'


def test_format_int_rejects_non_integer():
    import pytest

    with pytest.raises(ValueError):
        format_value("abc", "int")


def test_current_value_from_raw_data():
    data = {"wake": {"arm": "always"}}
    item = {"section": "wake", "key": "arm", "default": "manual"}
    assert current_value(data, item) == "always"


def test_current_value_falls_back_to_default():
    item = {"section": "wake", "key": "arm", "default": "manual"}
    assert current_value({}, item) == "manual"


def test_schema_covers_user_keys():
    keys = {(i["section"], i["key"]) for i in SCHEMA}
    expected = {
        ("wake", "arm"),
        ("notify", "enabled"),
        ("general", "refresh_interval_minutes"),
        ("general", "max_refresh_count"),
        ("display", "recap_style"),
        ("general", "language"),
        ("general", "cache_ttl_minutes"),
    }
    assert keys == expected
    # grace_seconds 는 advanced — 제외
    assert ("wake", "grace_seconds") not in keys


def test_schema_items_have_required_fields():
    for item in SCHEMA:
        assert {"section", "key", "label", "type", "default"} <= item.keys()
        assert item["type"] in ("choice", "bool", "int", "str")


def test_apply_changes_creates_file_and_writes(tmp_path):
    path = tmp_path / "config.toml"
    apply_changes(path, [(_ARM, "always")])
    text = path.read_text()
    assert 'arm = "always"' in text
    # 템플릿의 다른 키 보존
    assert "refresh_interval_minutes" in text


def test_apply_changes_preserves_user_edits(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[wake]\narm = "manual"\ngrace_seconds = 99\n\n[display]\nrecap_style = "compact"\n'
    )
    apply_changes(path, [(_RECAP, "box")])
    text = path.read_text()
    assert 'recap_style = "box"' in text
    assert "grace_seconds = 99" in text  # 사용자 편집 advanced 키 보존


def test_prompt_item_returns_selected_option():
    out = prompt_item(_ARM, "manual", input_fn=lambda _: "2")
    assert out == "always"  # options[1]


def test_prompt_item_enter_keeps_current():
    out = prompt_item(_ARM, "manual", input_fn=lambda _: "")
    assert out is None


def test_prompt_item_free_input_for_int():
    item = next(i for i in SCHEMA if i["key"] == "cache_ttl_minutes")
    out = prompt_item(item, 60, input_fn=lambda _: "120")
    assert out == "120"  # 옵션 밖 직접 입력


def test_prompt_item_invalid_number_keeps_current():
    out = prompt_item(_ARM, "manual", input_fn=lambda _: "9")  # 범위 밖, choice 라 자유입력 불가
    assert out is None


_TTL = next(i for i in SCHEMA if i["key"] == "cache_ttl_minutes")
_LANG = next(i for i in SCHEMA if i["key"] == "language")


def test_prompt_item_rejects_non_integer_free_input():
    # int 항목에 "9.5"/"abc" 직접입력 → 크래시 대신 유지
    assert prompt_item(_TTL, 60, input_fn=lambda _: "9.5") is None
    assert prompt_item(_TTL, 60, input_fn=lambda _: "abc") is None


def test_prompt_item_rejects_non_positive_int():
    assert prompt_item(_TTL, 60, input_fn=lambda _: "-5") is None
    assert prompt_item(_TTL, 60, input_fn=lambda _: "0") is None


def test_prompt_item_rejects_newline_or_quote_in_str():
    # language 자유입력에 개행/따옴표 → TOML 깨짐 방지로 거부
    assert prompt_item(_LANG, "en", input_fn=lambda _: 'en"\narm = "always') is None
    assert prompt_item(_LANG, "en", input_fn=lambda _: 'a"b') is None


def test_prompt_item_accepts_valid_free_int():
    assert prompt_item(_TTL, 60, input_fn=lambda _: "120") == "120"


def test_apply_changes_returns_false_on_oserror(tmp_path):
    path = tmp_path / "config.toml"
    path.mkdir()  # 디렉터리 → read/write 불가 (IsADirectoryError ⊂ OSError)
    result = apply_changes(path, [(_ARM, "always")])
    assert result is False  # 예외 전파 대신 False


def test_run_tui_applies_only_changed(tmp_path):
    path = tmp_path / "config.toml"
    inputs = iter(["2", "", "", "", "", "", ""])  # arm=always, 나머지 유지
    changes = run_tui(path, input_fn=lambda _: next(inputs))
    assert len(changes) == 1
    assert changes[0][0]["key"] == "arm"
    assert 'arm = "always"' in path.read_text()


def test_run_tui_no_change_when_all_kept(tmp_path):
    path = tmp_path / "config.toml"
    changes = run_tui(path, input_fn=lambda _: "")  # 전부 Enter
    assert changes == []
    assert not path.exists()  # 변경 없으면 파일도 안 만듦


def test_run_tui_selecting_same_value_is_not_a_change(tmp_path):
    path = tmp_path / "config.toml"
    # arm 의 현재값(기본 manual)을 그대로 1번으로 다시 선택 → 변경 아님
    inputs = iter(["1", "", "", "", "", "", ""])
    changes = run_tui(path, input_fn=lambda _: next(inputs))
    assert changes == []


def test_main_hint_prints_launch_command(capsys):
    rc = main(["--hint"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cn_config.py" in out  # 실행 경로 안내
    assert "터미널" in out

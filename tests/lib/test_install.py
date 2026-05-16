"""Tests for lib/install.py — `cn install` / `cn uninstall` CLI (TECH_SPEC §7)."""
import io
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.install import (  # noqa: E402
    CN_HOOK_MARKER,
    install_main,
    uninstall_main,
)


@pytest.fixture
def isolated_env(cn_root, monkeypatch, tmp_path):
    """CN_ROOT + CN_CLAUDE_ROOT 격리. conftest 의 autouse 가 만든 디렉토리와
    충돌 안 하도록 fresh path 사용."""
    claude_root = tmp_path / "fresh_claude"
    claude_root.mkdir()
    monkeypatch.setenv("CN_CLAUDE_ROOT", str(claude_root))
    return claude_root


def _settings(claude_root: Path) -> dict:
    return json.loads((claude_root / "settings.json").read_text())


class TestInstallFresh:
    def test_creates_settings_with_stop_hook(self, isolated_env, capsys):
        rc = install_main()
        assert rc == 0
        s = _settings(isolated_env)
        stop = s["hooks"]["Stop"]
        assert len(stop) == 1
        assert len(stop[0]["hooks"]) == 1
        h = stop[0]["hooks"][0]
        assert CN_HOOK_MARKER in h["command"]
        assert h["asyncRewake"] is True
        assert h["timeout"] == 3600
        out = capsys.readouterr().out
        assert "설치 완료" in out
        assert "새 chat 세션" in out


class TestInstallIdempotent:
    def test_does_not_duplicate_when_already_installed(self, isolated_env, capsys):
        install_main()  # 첫 설치
        rc = install_main()  # 두 번째
        assert rc == 0
        out = capsys.readouterr().out
        assert "이미 설치됨" in out
        s = _settings(isolated_env)
        assert len(s["hooks"]["Stop"]) == 1
        assert len(s["hooks"]["Stop"][0]["hooks"]) == 1


class TestInstallConflict:
    def test_warns_when_other_stop_hook_exists(self, isolated_env, capsys):
        # 다른 사용자 hook 미리 등록
        sp = isolated_env / "settings.json"
        sp.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]
            }
        }))
        rc = install_main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "기존 Stop hook" in err
        # cn hook 추가 안 됨
        assert not any(
            CN_HOOK_MARKER in h.get("command", "")
            for entry in _settings(isolated_env)["hooks"]["Stop"]
            for h in entry.get("hooks", [])
        )

    def test_force_overrides_conflict(self, isolated_env, capsys):
        sp = isolated_env / "settings.json"
        sp.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]
            }
        }))
        rc = install_main(force=True)
        assert rc == 0
        # cn hook + 기존 hook 공존
        all_cmds = [
            h["command"]
            for entry in _settings(isolated_env)["hooks"]["Stop"]
            for h in entry.get("hooks", [])
        ]
        assert any("echo other" in c for c in all_cmds)
        assert any(CN_HOOK_MARKER in c for c in all_cmds)


class TestStaleDaemonDetect:
    def test_warns_when_v02x_lock_exists(self, isolated_env, cn_root, capsys):
        (cn_root / "lock").write_text("stale")
        install_main()
        out = capsys.readouterr().out
        assert "v0.2.x daemon 잔존" in out
        assert "pkill" in out
        # install 자체는 진행됨
        assert _settings(isolated_env)["hooks"]["Stop"]

    def test_warns_when_v02x_state_dir_has_files(self, isolated_env, cn_root, capsys):
        sd = cn_root / "state"
        sd.mkdir(exist_ok=True)
        (sd / "session.json").write_text("{}")
        install_main()
        out = capsys.readouterr().out
        assert "v0.2.x daemon 잔존" in out

    def test_silent_when_no_stale_artifacts(self, isolated_env, cn_root, capsys):
        # cn_root 의 state/ 가 conftest 에 의해 비어있음
        install_main()
        out = capsys.readouterr().out
        assert "v0.2.x daemon" not in out


class TestUninstall:
    def test_removes_only_cn_hook(self, isolated_env, capsys):
        # 미리 install + 다른 hook 도 등록
        install_main()
        s = _settings(isolated_env)
        s["hooks"]["Stop"].append({
            "hooks": [{"type": "command", "command": "echo other"}]
        })
        (isolated_env / "settings.json").write_text(json.dumps(s, indent=2))

        rc = uninstall_main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "제거 완료" in out
        # cn 만 제거, 다른 hook 보존
        all_cmds = [
            h["command"]
            for entry in _settings(isolated_env)["hooks"].get("Stop", [])
            for h in entry.get("hooks", [])
        ]
        assert not any(CN_HOOK_MARKER in c for c in all_cmds)
        assert any("echo other" in c for c in all_cmds)

    def test_silent_when_settings_missing(self, isolated_env, capsys):
        rc = uninstall_main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "settings.json 없음" in out

    def test_silent_when_no_cn_hook(self, isolated_env, capsys):
        sp = isolated_env / "settings.json"
        sp.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]
            }
        }))
        rc = uninstall_main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "변경 X" in out

    def test_removes_empty_stop_section(self, isolated_env):
        """uninstall 후 Stop hook list 가 비면 Stop key 자체 제거."""
        install_main()
        uninstall_main()
        s = _settings(isolated_env)
        # hooks.Stop key 자체가 사라짐
        assert "Stop" not in s.get("hooks", {})


class TestSettingsCorrupt:
    def test_install_aborts_on_invalid_json(self, isolated_env, capsys):
        (isolated_env / "settings.json").write_text("{invalid")
        rc = install_main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "settings.json 파싱 실패" in err


class TestPreserveOtherKeys:
    def test_install_preserves_non_hook_top_level_keys(self, isolated_env):
        """install 이 enabledPlugins / pluginConfigs 등 top-level key 보존."""
        sp = isolated_env / "settings.json"
        sp.write_text(json.dumps({
            "enabledPlugins": {"cache-necromancer@cache-necromancer-marketplace": True},
            "pluginConfigs": {"cache-necromancer": {"mode": "auto"}},
            "model": "claude-opus-4-7",
        }))
        install_main()
        s = _settings(isolated_env)
        assert s["enabledPlugins"] == {
            "cache-necromancer@cache-necromancer-marketplace": True
        }
        assert s["pluginConfigs"] == {"cache-necromancer": {"mode": "auto"}}
        assert s["model"] == "claude-opus-4-7"
        # Stop hook 추가됐음
        assert s["hooks"]["Stop"]

    def test_uninstall_preserves_non_hook_top_level_keys(self, isolated_env):
        install_main()
        # 다른 top-level key 추가
        s = _settings(isolated_env)
        s["enabledPlugins"] = {"some-other-plugin": True}
        s["model"] = "claude-sonnet-4-6"
        (isolated_env / "settings.json").write_text(json.dumps(s, indent=2))

        uninstall_main()
        s2 = _settings(isolated_env)
        assert s2["enabledPlugins"] == {"some-other-plugin": True}
        assert s2["model"] == "claude-sonnet-4-6"

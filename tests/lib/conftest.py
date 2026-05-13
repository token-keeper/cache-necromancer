"""Shared fixtures for lib/ tests."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_plugin_env(monkeypatch):
    """Ensure CLAUDE_PLUGIN_OPTION_MODE doesn't leak between tests.

    This file's tests intentionally set/unset the env var as needed.
    Other lib/ tests should not be affected by external env state.
    """
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MODE", raising=False)

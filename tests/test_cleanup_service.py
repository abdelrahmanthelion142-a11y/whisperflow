"""Tests for the Langfuse cleanup prompt update mechanism."""

import sys
from unittest.mock import MagicMock

import pytest

from app.services.cleanup import _FALLBACK_SYSTEM_PROMPT, update_cleanup_prompt


@pytest.fixture(autouse=True)
def _fake_langfuse_module():
    """Inject a fake ``langfuse`` module so imports succeed in tests."""
    original = sys.modules.get("langfuse")
    sys.modules["langfuse"] = MagicMock()
    yield
    if original is not None:
        sys.modules["langfuse"] = original
    else:
        sys.modules.pop("langfuse", None)


def test_update_prompt_creates_version_with_fallback_text(monkeypatch):
    """update_cleanup_prompt must call create_prompt with _FALLBACK_SYSTEM_PROMPT."""
    import langfuse

    mock_client = MagicMock()
    langfuse.get_client.return_value = mock_client

    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_PUBLIC_KEY",
        MagicMock(get_secret_value=lambda: "pk-test"),
    )
    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_SECRET_KEY",
        MagicMock(get_secret_value=lambda: "sk-test"),
    )
    monkeypatch.setattr(
        "app.services.cleanup.settings.CLEANUP_PROMPT_NAME",
        "whisperflow-cleanup",
    )

    result = update_cleanup_prompt()

    assert result is True
    mock_client.create_prompt.assert_called_once_with(
        name="whisperflow-cleanup",
        type="text",
        prompt=_FALLBACK_SYSTEM_PROMPT,
        labels=["production"],
    )


def test_fallback_prompt_has_no_token_clause():
    """_FALLBACK_SYSTEM_PROMPT must not contain any TOKEN references."""
    assert "TOKEN" not in _FALLBACK_SYSTEM_PROMPT
    assert "token" not in _FALLBACK_SYSTEM_PROMPT.lower()


def test_update_prompt_returns_false_on_langfuse_error(monkeypatch):
    """When Langfuse raises, update_cleanup_prompt must return False."""
    import langfuse

    langfuse.get_client.side_effect = RuntimeError("unreachable")

    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_PUBLIC_KEY",
        MagicMock(get_secret_value=lambda: "pk-test"),
    )
    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_SECRET_KEY",
        MagicMock(get_secret_value=lambda: "sk-test"),
    )

    result = update_cleanup_prompt()
    assert result is False


def test_update_prompt_returns_false_on_create_prompt_error(monkeypatch):
    """When create_prompt raises, update_cleanup_prompt must return False."""
    import langfuse

    mock_client = MagicMock()
    mock_client.create_prompt.side_effect = RuntimeError("api error")
    langfuse.get_client.return_value = mock_client

    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_PUBLIC_KEY",
        MagicMock(get_secret_value=lambda: "pk-test"),
    )
    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_SECRET_KEY",
        MagicMock(get_secret_value=lambda: "sk-test"),
    )

    result = update_cleanup_prompt()
    assert result is False


def test_update_prompt_returns_false_on_empty_credentials(monkeypatch):
    """When credentials are empty, update_cleanup_prompt must return False."""
    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_PUBLIC_KEY",
        MagicMock(get_secret_value=lambda: ""),
    )
    monkeypatch.setattr(
        "app.services.cleanup.settings.LANGFUSE_SECRET_KEY",
        MagicMock(get_secret_value=lambda: ""),
    )

    result = update_cleanup_prompt()
    assert result is False

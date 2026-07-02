"""Unit tests for CleanupService.

Verifies the three-step pipeline (pre-mask awareness, LLM call, post-LLM
token validation with retry) and that Langfuse unavailability is handled
gracefully without breaking cleanup.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.schemas.Transcription import CleanupResult
from app.services.cleanup import CleanupService


class _ScriptedCleanupService(CleanupService):
    """CleanupService subclass that returns scripted outputs from _run_agent."""

    def __init__(
        self,
        outputs: list[str],
        model: str = "test-model",
    ) -> None:
        super().__init__(model=model, max_retries=2)
        self._scripted = list(outputs)
        self.calls: list[str] = []

    async def _run_agent(self, text: str) -> str:
        self.calls.append(text)
        if not self._scripted:
            return self.calls[-1]  # type: ignore[return-value]
        return self._scripted.pop(0)


@pytest.mark.asyncio
async def test_clean_returns_text_when_all_tokens_survive() -> None:
    service = _ScriptedCleanupService(
        outputs=["Hello ⟦TOKEN0⟧, how are you?"],
    )

    result = await service.clean(
        text="Hello ⟦TOKEN0⟧, how are you?",
        expected_tokens=["⟦TOKEN0⟧"],
    )

    assert isinstance(result, CleanupResult)
    assert result.cleaned_text == "Hello ⟦TOKEN0⟧, how are you?"
    assert result.model == "test-model"
    assert result.latency_ms >= 0
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_clean_retries_when_token_corrupted() -> None:
    service = _ScriptedCleanupService(
        outputs=[
            "Hello TOKEN0, how are you?",  # token corrupted on first try
            "Hello ⟦TOKEN0⟧, how are you?",  # retry preserves token
        ],
    )

    result = await service.clean(
        text="Hello ⟦TOKEN0⟧, how are you?",
        expected_tokens=["⟦TOKEN0⟧"],
    )

    assert result.cleaned_text == "Hello ⟦TOKEN0⟧, how are you?"
    assert len(service.calls) == 2


@pytest.mark.asyncio
async def test_clean_retries_until_max_attempts_exhausted() -> None:
    service = _ScriptedCleanupService(
        outputs=[
            "Hello TOKEN0",  # missing ⟦TOKEN0⟧
            "Hello TOKEN0",  # still missing
            "Hello TOKEN0",  # still missing — no more retries
        ],
    )

    result = await service.clean(
        text="Hello ⟦TOKEN0⟧",
        expected_tokens=["⟦TOKEN0⟧"],
    )

    # After max_retries, the service still returns the last output.
    assert result.cleaned_text == "Hello TOKEN0"
    # 1 initial + 2 retries = 3 total calls
    assert len(service.calls) == 3


@pytest.mark.asyncio
async def test_clean_with_no_expected_tokens_does_not_retry() -> None:
    service = _ScriptedCleanupService(
        outputs=["Cleaned text without any tokens."],
    )

    result = await service.clean(
        text="raw text",
        expected_tokens=[],
    )

    assert result.cleaned_text == "Cleaned text without any tokens."
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_clean_validates_multiple_tokens_sequentially() -> None:
    """Each token is checked independently. Only missing ones trigger retry."""
    service = _ScriptedCleanupService(
        outputs=[
            "I am ⟦TOKEN0⟧ and you are TOKEN1",  # TOKEN1 corrupted
            "I am ⟦TOKEN0⟧ and you are ⟦TOKEN1⟧",  # both preserved
        ],
    )

    result = await service.clean(
        text="I am ⟦TOKEN0⟧ and you are ⟦TOKEN1⟧",
        expected_tokens=["⟦TOKEN0⟧", "⟦TOKEN1⟧"],
    )

    assert result.cleaned_text == "I am ⟦TOKEN0⟧ and you are ⟦TOKEN1⟧"
    assert len(service.calls) == 2


@pytest.mark.asyncio
async def test_clean_duplicate_snippet_shortcut_validates_each_token() -> None:
    """Two snippets with the same shortcut still produce two independent tokens."""
    service = _ScriptedCleanupService(
        outputs=[
            "Call ⟦TOKEN0⟧ then call TOKEN0 again",  # second instance corrupted
            "Call ⟦TOKEN0⟧ then call ⟦TOKEN0⟧ again",
        ],
    )

    result = await service.clean(
        text="Call ⟦TOKEN0⟧ then call ⟦TOKEN0⟧ again",
        expected_tokens=["⟦TOKEN0⟧", "⟦TOKEN0⟧"],
    )

    assert result.cleaned_text == "Call ⟦TOKEN0⟧ then call ⟦TOKEN0⟧ again"
    assert len(service.calls) == 2


@pytest.mark.asyncio
async def test_clean_does_not_retry_when_no_missing_tokens() -> None:
    """If all tokens survive on first try, no retry happens."""
    service = _ScriptedCleanupService(
        outputs=[
            "Result with ⟦TOKEN0⟧ and ⟦TOKEN1⟧ intact",
            "SHOULD NOT BE CALLED",
        ],
    )

    result = await service.clean(
        text="Result with ⟦TOKEN0⟧ and ⟦TOKEN1⟧ intact",
        expected_tokens=["⟦TOKEN0⟧", "⟦TOKEN1⟧"],
    )

    assert len(service.calls) == 1
    assert result.cleaned_text == "Result with ⟦TOKEN0⟧ and ⟦TOKEN1⟧ intact"


def test_constructor_uses_default_model_from_settings() -> None:
    """Without an explicit model, CleanupService pulls from settings."""
    from app.core.config import settings

    class _NullService(CleanupService):
        async def _run_agent(self, text: str) -> str:  # pragma: no cover
            return text

    service = _NullService()
    assert service._model_name == settings.CLEANUP_LLM_MODEL


def test_langfuse_failure_does_not_break_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CleanupService must build even if Langfuse is unreachable."""

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("langfuse down")

    # Patch the module-level _build_agent path used by the constructor.
    monkeypatch.setattr("app.services.cleanup._try_load_langfuse_prompt", _raise)

    service = CleanupService(model="gpt-4o-mini")
    assert service._model_name == "gpt-4o-mini"


def test_try_load_langfuse_prompt_handles_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the langfuse package can't be imported, fall back gracefully."""
    import builtins
    original_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("no langfuse")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    from app.services.cleanup import _try_load_langfuse_prompt

    prompt = _try_load_langfuse_prompt()
    assert prompt  # falls back to a non-empty string

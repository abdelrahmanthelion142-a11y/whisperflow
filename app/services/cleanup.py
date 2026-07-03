"""LLM cleanup service backed by a Pydantic AI agent.

Receives raw Whisper text and returns the LLM's cleaned version.

Langfuse is used to manage the cleanup system prompt in production.
If Langfuse is unreachable or unconfigured, the service logs a warning
and falls back to a baked-in prompt — the pipeline keeps running.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.config import settings
from app.schemas.Transcription import CleanupResult

log = logging.getLogger(__name__)


_FALLBACK_SYSTEM_PROMPT = (
    "You are a dictation cleanup assistant. Fix grammar and punctuation in the "
    "user's transcribed text. Return only the cleaned text."
)


def _try_load_langfuse_prompt() -> str:
    """Return the Langfuse-managed cleanup prompt, falling back gracefully."""
    try:
        from langfuse import get_client
    except ImportError:
        log.warning("langfuse package unavailable; using fallback cleanup prompt")
        return _FALLBACK_SYSTEM_PROMPT

    public_key = settings.LANGFUSE_PUBLIC_KEY.get_secret_value()
    secret_key = settings.LANGFUSE_SECRET_KEY.get_secret_value()
    if not public_key or not secret_key:
        log.warning("Langfuse credentials not configured; using fallback prompt")
        return _FALLBACK_SYSTEM_PROMPT

    try:
        client = get_client()
        if not client.auth_check():
            log.warning("Langfuse auth check failed; using fallback prompt")
            return _FALLBACK_SYSTEM_PROMPT
        prompt = client.get_prompt(settings.CLEANUP_PROMPT_NAME)
        compiled = prompt.compile()
    except Exception as exc:  # noqa: BLE001
        log.warning("Langfuse unavailable (%s); using fallback prompt", exc)
        return _FALLBACK_SYSTEM_PROMPT

    if not compiled:
        log.warning("Langfuse returned empty prompt; using fallback prompt")
        return _FALLBACK_SYSTEM_PROMPT
    return str(compiled)


class CleanupService:
    """Sends text to a Pydantic AI agent for cleanup."""

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or settings.CLEANUP_LLM_MODEL
        self._agent: Any = None

    def _build_agent(self) -> Any:
        """Construct the Pydantic AI agent. Lazy so construction is cheap."""
        from pydantic_ai import Agent

        system_prompt = _try_load_langfuse_prompt()
        return Agent(self._model_name, system_prompt=system_prompt)

    async def _run_agent(self, text: str) -> str:
        """Send text to the LLM and return the cleaned text.

        Subclasses can override this to script LLM responses in tests.
        """
        if self._agent is None:
            self._agent = self._build_agent()
        result = await self._agent.run(text)
        return str(result.output)

    async def clean(self, text: str) -> CleanupResult:
        """Run the LLM cleanup and return the result."""
        start = time.perf_counter()
        cleaned = await self._run_agent(text)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return CleanupResult(
            cleaned_text=cleaned,
            latency_ms=latency_ms,
            model=self._model_name,
        )

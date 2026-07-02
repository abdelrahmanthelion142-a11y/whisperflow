"""LLM cleanup service backed by a Pydantic AI agent.

Implements the three-step snippet pipeline described in PRD #1 / issue #4:

1. The coordinator passes a list of expected ``⟦TOKEN⟧`` placeholders
   that were already substituted into the masked text.
2. ``CleanupService.clean`` invokes the agent, then checks the output
   to confirm every expected token survived. Missing tokens trigger
   automatic retries.
3. The coordinator performs the final ``⟦TOKEN⟧`` → expansion swap
   (and the catch-all replacement for any trigger phrases the LLM
   silently corrected).

Langfuse is used to manage the cleanup system prompt in production.
If Langfuse is unreachable or unconfigured, the service logs a warning
and falls back to a baked-in prompt — the pipeline keeps running.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.schemas.Transcription import CleanupResult

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


_FALLBACK_SYSTEM_PROMPT = (
    "You are a dictation cleanup assistant. Fix grammar and punctuation in the "
    "user's transcribed text. CRITICAL: do not modify, remove, or replace any "
    "text matching the pattern '⟦TOKEN⟧' — these are user-defined snippet "
    "placeholders that must survive verbatim. Return only the cleaned text."
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
    """Sends masked text to a Pydantic AI agent and validates snippet tokens."""

    def __init__(self, model: str | None = None, max_retries: int = 2) -> None:
        self._model_name = model or settings.CLEANUP_LLM_MODEL
        self._max_retries = max_retries
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

    async def clean(
        self,
        text: str,
        expected_tokens: list[str] | None = None,
    ) -> CleanupResult:
        """Run the LLM cleanup and verify snippet tokens survive.

        ``expected_tokens`` is an ordered list of ``⟦TOKEN⟧`` placeholders
        the coordinator substituted into the text before the call. Each
        token is verified sequentially in order: a token that survives
        in the output is stripped from the output (and the tracking list)
        before the next token is checked. This means a token expected
        N times must appear N times in the output, even if multiple
        snippets share the same shortcut.

        Missing tokens trigger up to ``max_retries`` retries of the LLM
        call. If a token is still missing after all retries, the cleaned
        text is returned as-is — the post-swap will be a no-op for that
        snippet.
        """
        expected = list(expected_tokens or [])

        start = time.perf_counter()
        cleaned = await self._run_agent(text)
        for attempt in range(self._max_retries):
            if not expected:
                break
            missing = self._consume_tokens(cleaned, expected)
            if not missing:
                break
            log.warning(
                "Cleanup LLM corrupted %d snippet token(s) on attempt %d; retrying",
                len(missing),
                attempt + 1,
            )
            cleaned = await self._run_agent(text)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return CleanupResult(
            cleaned_text=cleaned,
            latency_ms=latency_ms,
            model=self._model_name,
        )

    @staticmethod
    def _consume_tokens(text: str, expected: list[str]) -> list[str]:
        """Strip confirmed tokens from ``text`` and ``expected``.

        Returns the list of tokens that could not be confirmed in the
        text. For each expected token, in order: if the token is in
        the text, one occurrence is removed and the token is dropped
        from the missing list; otherwise the token is reported as
        missing and remains in the tracking list (so the caller can
        retry).
        """
        missing: list[str] = []
        remaining: list[str] = []
        for token in expected:
            if token in text:
                text = text.replace(token, "", 1)
            else:
                missing.append(token)
                remaining.append(token)
        expected[:] = remaining
        return missing

"""Pipeline orchestrator for transcribe → cleanup → expand → persist.

Composes the small single-purpose services into the full end-to-end
dictation flow described in PRD #1 / issue #4:

1. Validate + transcribe audio via :class:`TranscriptionService`.
2. If snippets are enabled, fetch the user's active snippets and
   pre-mask every detected trigger phrase with a ``⟦TOKEN⟧`` placeholder.
3. If cleanup is enabled, send the masked text to
   :class:`CleanupService` (which verifies snippet tokens survive).
4. Post-swap: replace surviving tokens with their expansions, and
   catch-all any trigger phrase the LLM silently rewrote.
5. Persist ``voice_messages``, ``transcriptions``, ``cleanups``, and
   the two junction tables (``transcription_snippets``,
   ``cleanup_snippets``).
6. Return a :class:`TranscriptionResponse` with both the raw and
   processed text.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cleanup_snippets import CleanupSnippet
from app.models.cleanups import Cleanup
from app.models.snippets import Snippet
from app.models.transcription_snippets import TranscriptionSnippet
from app.models.transcriptions import Transcription
from app.models.voice_messages import VoiceMessage
from app.schemas.Transcription import CleanupResult, TranscriptionResponse
from app.services.cleanup import CleanupService
from app.services.protocols import UploadLike
from app.services.snippets import SnippetService
from app.services.transcription import TranscriptionService

if TYPE_CHECKING:
    pass


class _InMemoryUpload:
    """An UploadFile-like wrapper that returns a pre-read byte buffer."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self, _size: int = -1) -> bytes:
        return self._content


class TranscriptionCoordinator:
    """Orchestrates transcription, cleanup, snippet expansion, and persistence."""

    def __init__(
        self,
        db: AsyncSession,
        transcription_service: TranscriptionService,
        snippet_service: SnippetService,
        cleanup_service: CleanupService,
    ) -> None:
        self.db = db
        self.transcription_service = transcription_service
        self.snippet_service = snippet_service
        self.cleanup_service = cleanup_service

    async def process_audio(
        self,
        user_id: int,
        file: UploadLike,
        language: str,
        clean_enabled: bool,
        snippets_enabled: bool,
    ) -> TranscriptionResponse:
        filename = file.filename or "audio"
        content = await file.read()
        file_size = len(content)

        # 1. Transcribe
        result = await self.transcription_service.transcribe_audio(
            file=_InMemoryUpload(filename=filename, content=content),
            language=language,
        )
        raw_text = result.text

        # 2. Snippet pre-mask
        active_snippets: list[Snippet] = []
        if snippets_enabled:
            active_snippets = await self.snippet_service.get_active(
                user_id=user_id
            )

        (
            masked_text,
            token_to_snippet,
            used_snippet_ids,
        ) = self._pre_mask(raw_text, active_snippets)
        expected_tokens = list(token_to_snippet.keys())

        # 3. Cleanup (LLM call)
        cleanup_result: CleanupResult | None = None
        if clean_enabled:
            cleanup_result = await self.cleanup_service.clean(
                masked_text, expected_tokens
            )

        # 4. Post-swap
        cleaned_text: str | None = None
        if cleanup_result is not None:
            cleaned_text = self._post_swap(
                cleanup_result.cleaned_text,
                active_snippets,
                used_snippet_ids,
                token_to_snippet,
            )
        elif snippets_enabled:
            # No LLM, but snippets were requested. Apply the post-swap
            # to the raw text so we still surface a "processed" string
            # to the user (even if no expansion matched).
            cleaned_text = self._post_swap(
                raw_text,
                active_snippets,
                used_snippet_ids,
                token_to_snippet,
            )

        # 5. Persist
        voice_message = VoiceMessage(
            user_id=user_id,
            filename=filename,
            language=language or "auto",
            snippets_enabled=snippets_enabled,
            clean_enabled=clean_enabled,
            file_size_bytes=file_size,
            audio_duration_secs=result.duration_secs,
        )
        self.db.add(voice_message)
        await self.db.flush()

        transcription = Transcription(
            voice_message_id=voice_message.id,
            raw_text=raw_text,
            detected_language=result.language,
            latency_ms=result.latency_ms,
            model=TranscriptionService.MODEL_NAME,
        )
        if used_snippet_ids:
            transcription.snippet_links = [
                TranscriptionSnippet(snippet_id=sid) for sid in used_snippet_ids
            ]
        self.db.add(transcription)
        await self.db.flush()

        if cleanup_result is not None:
            cleanup = Cleanup(
                voice_message_id=voice_message.id,
                cleaned_text=cleaned_text,
                model=cleanup_result.model,
                latency_ms=cleanup_result.latency_ms,
            )
            if used_snippet_ids:
                cleanup.snippet_links = [
                    CleanupSnippet(snippet_id=sid) for sid in used_snippet_ids
                ]
            self.db.add(cleanup)

        await self.db.commit()
        await self.db.refresh(transcription)

        # 6. Return
        return TranscriptionResponse(
            success=True,
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            detected_language=result.language,
            audio_duration_secs=result.duration_secs,
            latency_ms=result.latency_ms,
        )

    @staticmethod
    def _pre_mask(
        text: str,
        snippets: list[Snippet],
    ) -> tuple[str, dict[str, Snippet], list[int]]:
        """Replace each detected snippet trigger with a ``⟦TOKEN⟧``.

        Returns:
            masked_text: the text with triggers replaced by tokens
            token_to_snippet: ordered mapping from token placeholder to
                the :class:`Snippet` whose expansion belongs there
            used_snippet_ids: snippet IDs that were masked, in order
        """
        # Process longer shortcuts first so "myemail" wins over "my".
        ordered = sorted(
            snippets, key=lambda s: len(s.shortcut), reverse=True
        )
        token_to_snippet: dict[str, Snippet] = {}
        used_snippet_ids: list[int] = []
        masked = text
        token_idx = 0
        for snippet in ordered:
            pattern = re.compile(
                rf"\b{re.escape(snippet.shortcut)}\b", re.IGNORECASE
            )
            if not pattern.search(masked):
                continue
            token = f"⟦TOKEN{token_idx}⟧"
            token_to_snippet[token] = snippet
            used_snippet_ids.append(snippet.id)
            masked = pattern.sub(token, masked)
            token_idx += 1
        return masked, token_to_snippet, used_snippet_ids

    @staticmethod
    def _post_swap(
        text: str,
        snippets: list[Snippet],
        used_snippet_ids: list[int],
        token_to_snippet: dict[str, Snippet],
    ) -> str:
        """Replace surviving ``⟦TOKEN⟧`` placeholders with expansions.

        Also performs a catch-all pass: for every snippet that was
        detected in the input, look for the trigger phrase in the
        post-LLM text (the LLM may have silently corrected the
        shortcut to a more natural form) and replace any remaining
        occurrence with the expansion.
        """
        result = text
        for token, snippet in token_to_snippet.items():
            if token in result:
                result = result.replace(token, snippet.expansion, 1)

        used_snippets = [s for s in snippets if s.id in set(used_snippet_ids)]
        for snippet in used_snippets:
            pattern = re.compile(
                rf"\b{re.escape(snippet.shortcut)}\b", re.IGNORECASE
            )
            result = pattern.sub(snippet.expansion, result)
        return result

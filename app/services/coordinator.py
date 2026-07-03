"""Pipeline orchestrator for transcribe → cleanup → expand → persist.

Composes the small single-purpose services into the full end-to-end
dictation flow described in PRD #1 / issue #4:

1. Validate + transcribe audio via :class:`TranscriptionService`.
2. If snippets are enabled, fetch the user's active snippets.
3. If cleanup is enabled, send the raw Whisper text to
   :class:`CleanupService`.
4. Snippet expansion via a single regex pass on the final string
   (LLM output if cleanup ran, else raw Whisper text).
5. Persist ``voice_messages``, ``transcriptions``, ``cleanups``, and
   the two junction tables (``transcription_snippets``,
   ``cleanup_snippets``).
6. Return a :class:`TranscriptionResponse` with ``raw_text`` (literal
   Whisper or snippet-expanded when cleanup is off) and ``cleaned_text``
   (LLM output, optionally expanded, or ``None`` when cleanup is off).
"""
from __future__ import annotations

import re
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


def _expand_snippets(
    text: str,
    snippets: list[Snippet],
) -> tuple[str, list[int]]:
    """Expand snippet shortcuts in *text*.

    Returns ``(expanded_text, used_snippet_ids)``.

    Overlapping shortcuts resolve leftmost-longest: at each position the
    longest matching shortcut is expanded. A single ``re.sub`` pass with
    alternation (longest alternatives first) ensures non-overlapping
    leftmost-longest matching.
    """
    if not snippets:
        return text, []

    ordered = sorted(snippets, key=lambda s: len(s.shortcut), reverse=True)
    parts = [re.escape(s.shortcut) for s in ordered]
    pattern = re.compile(rf"\b({'|'.join(parts)})\b", re.IGNORECASE)

    snippet_by_lower: dict[str, Snippet] = {s.shortcut.lower(): s for s in snippets}
    used_ids: list[int] = []

    def _replacer(m: re.Match) -> str:
        key = m.group(0).lower()
        snippet = snippet_by_lower[key]
        if snippet.id not in used_ids:
            used_ids.append(snippet.id)
        return snippet.expansion

    expanded = pattern.sub(_replacer, text)
    return expanded, used_ids


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

        # 2. Fetch active snippets if enabled
        active_snippets: list[Snippet] = []
        if snippets_enabled:
            active_snippets = await self.snippet_service.list_all_active(
                user_id=user_id
            )

        # 3. Cleanup (LLM call) — receives raw Whisper text (no pre-mask)
        cleanup_result: CleanupResult | None = None
        if clean_enabled:
            cleanup_result = await self.cleanup_service.clean(raw_text)

        # 4. Determine response fields and which snippets were used
        response_raw_text: str = raw_text
        cleaned_text: str | None = None
        used_snippet_ids: list[int] = []

        if cleanup_result is not None:
            if snippets_enabled:
                swapped, used_snippet_ids = _expand_snippets(
                    cleanup_result.cleaned_text, active_snippets
                )
                cleaned_text = swapped
            else:
                cleaned_text = cleanup_result.cleaned_text
        else:
            if snippets_enabled:
                response_raw_text, used_snippet_ids = _expand_snippets(
                    raw_text, active_snippets
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
            raw_text=raw_text,  # Always literal Whisper output
            detected_language=result.language,
            latency_ms=result.latency_ms,
            model=TranscriptionService.MODEL_NAME,
        )
        if active_snippets and used_snippet_ids:
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
            if active_snippets and used_snippet_ids:
                cleanup.snippet_links = [
                    CleanupSnippet(snippet_id=sid) for sid in used_snippet_ids
                ]
            self.db.add(cleanup)

        await self.db.commit()
        await self.db.refresh(transcription)

        # 6. Return
        return TranscriptionResponse(
            success=True,
            raw_text=response_raw_text,
            cleaned_text=cleaned_text,
            detected_language=result.language,
            audio_duration_secs=result.duration_secs,
            latency_ms=result.latency_ms,
        )

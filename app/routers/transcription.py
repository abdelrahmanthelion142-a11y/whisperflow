from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.users import User
from app.core.llm import llm_client
from app.dependencies import get_db, get_current_user
from app.schemas.Transcription import TranscriptionResponse
from app.services.cleanup import CleanupService
from app.services.coordinator import TranscriptionCoordinator
from app.services.exceptions import (
    AudioTooLongException,
    FileTooLargeException,
    InvalidLanguageException,
    TranscriptionFailedException,
    UnsupportedFormatException,
)
from app.services.snippets import SnippetService
from app.services.transcription import TranscriptionService

router = APIRouter()


# Maps each service-layer exception to the HTTP status code the router returns.
_EXCEPTION_STATUS_CODES = {
    UnsupportedFormatException: status.HTTP_400_BAD_REQUEST,
    InvalidLanguageException: status.HTTP_400_BAD_REQUEST,
    AudioTooLongException: status.HTTP_400_BAD_REQUEST,
    FileTooLargeException: status.HTTP_413_CONTENT_TOO_LARGE,
    TranscriptionFailedException: status.HTTP_502_BAD_GATEWAY,
}


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def transcribe(
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, get_current_user],
    language: Annotated[str, Form()] = "auto",
    clean: Annotated[bool, Form()] = False,
    snippets: Annotated[bool, Form()] = True,
) -> TranscriptionResponse:
    transcription_service = TranscriptionService(whisper_client=llm_client)
    snippet_service = SnippetService(db=db)
    cleanup_service = CleanupService()
    coordinator = TranscriptionCoordinator(
        db=db,
        transcription_service=transcription_service,
        snippet_service=snippet_service,
        cleanup_service=cleanup_service,
    )

    try:
        return await coordinator.process_audio(
            user_id=current_user.id,
            file=file,  # type: ignore[arg-type]
            language=language,
            clean_enabled=clean,
            snippets_enabled=snippets,
        )
    except tuple(_EXCEPTION_STATUS_CODES) as exc:
        raise HTTPException(
            status_code=_EXCEPTION_STATUS_CODES[type(exc)],
            detail=str(exc),
        ) from exc

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import llm_client
from app.dependencies import get_db
from app.schemas.Transcription import TranscriptionResponse
from app.services.coordinator import TranscriptionCoordinator
from app.services.exceptions import (
    AudioTooLongException,
    FileTooLargeException,
    InvalidLanguageException,
    TranscriptionFailedException,
    UnsupportedFormatException,
)
from app.services.transcription import TranscriptionService

router = APIRouter()


# NOTE: user_id=0 is a placeholder. Authentication/authorization is out of
# scope for this issue; a future auth ticket will inject the current user.
@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def transcribe(
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    language: Annotated[str, Form()] = "auto",
    clean: Annotated[bool, Form()] = False,
    snippets: Annotated[bool, Form()] = True,
) -> TranscriptionResponse:
    transcription_service = TranscriptionService(whisper_client=llm_client)
    coordinator = TranscriptionCoordinator(
        db=db, transcription_service=transcription_service
    )

    try:
        return await coordinator.process_audio(
            user_id=0,
            file=file,  # type: ignore[arg-type]
            language=language,
            clean_enabled=clean,
            snippets_enabled=snippets,
        )
    except UnsupportedFormatException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except InvalidLanguageException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except AudioTooLongException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except FileTooLargeException as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except TranscriptionFailedException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


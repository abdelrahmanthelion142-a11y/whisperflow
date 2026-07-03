"""Pydantic schemas for the voice-message history endpoint."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VoiceMessageHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    language: str
    audio_duration_secs: float
    created_at: datetime
    has_transcription: bool
    has_cleanup: bool
    text: str | None = None

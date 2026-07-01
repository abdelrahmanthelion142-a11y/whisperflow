from pydantic import BaseModel, ConfigDict, Field


class TranscriptionResult(BaseModel):
    text: str
    language: str | None
    duration_secs: float
    latency_ms: float


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool = True
    raw_text: str
    detected_language: str | None
    audio_duration_secs: float = Field(...)
    latency_ms: float

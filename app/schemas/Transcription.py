from pydantic import BaseModel, ConfigDict, Field


class TranscriptionResult(BaseModel):
    text: str
    language: str | None
    duration_secs: float
    latency_ms: float


class CleanupResult(BaseModel):
    cleaned_text: str
    latency_ms: float
    model: str


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool = True
    raw_text: str
    cleaned_text: str | None = None
    detected_language: str | None
    audio_duration_secs: float = Field(...)
    latency_ms: float

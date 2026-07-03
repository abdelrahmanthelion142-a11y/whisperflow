from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.db.database import engine
from app.routers.transcription import router as TranscriptionRouter
from app.routers.users import router as UserRouter
from app.routers.snippets import router as SnippetRouter
from app.routers.voice_messages import router as VoiceMessageRouter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield

    await engine.dispose()


app = FastAPI(lifespan=lifespan)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(UserRouter, tags=["users"])
api_v1_router.include_router(TranscriptionRouter, tags=["transcription"])
api_v1_router.include_router(SnippetRouter, tags=["snippets"])
api_v1_router.include_router(VoiceMessageRouter, tags=["voice-messages"])

app.include_router(api_v1_router)

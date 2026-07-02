from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import engine
from app.routers.transcription import router as TranscriptionRouter
from app.routers.users import router as UserRouter
from app.routers.snippets import router as SnippetRouter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield

    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.include_router(UserRouter, prefix="/api/users", tags=["users"])
app.include_router(
    TranscriptionRouter, prefix="/api/v1", tags=["transcription"]
)
app.include_router(SnippetRouter, prefix="/api/snippets", tags=["snippets"])

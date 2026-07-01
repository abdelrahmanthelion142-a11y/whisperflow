from contextlib import asynccontextmanager
from app.db.database import engine
from fastapi import FastAPI
from app.routers.users import router as UserRouter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield

    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.include_router(UserRouter, prefix="/api/users", tags=["users"])

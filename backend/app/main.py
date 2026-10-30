"""PawPath (댕댕 산책각) API 서버 진입점."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import api, models  # noqa: F401  models는 테이블 등록을 위해 불러온다
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.seed import seed_all


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_all(db)
    yield


app = FastAPI(
    title="PawPath API",
    description="댕댕 산책각 - AI-Powered Personalized Pet Walking Recommendation",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router)

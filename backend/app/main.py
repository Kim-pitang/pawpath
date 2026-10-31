"""PawPath (댕댕 산책각) API 서버 진입점."""
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import api, models  # noqa: F401  models는 테이블 등록을 위해 불러온다
from app.config import get_settings
from app.database import SessionLocal, engine
from app.migrations import ensure_schema
from app.seed import seed_all
from app.services import backup_service

# 가장 긴 산책길(10만 지점)을 JSON으로 보낼 때 들어가는 크기를 기준으로 잡았다.
MAX_REQUEST_BYTES = 25 * 1024 * 1024
GOOGLE_CALLBACK_PATH = "/api/auth/google/callback"
# 백업할 때가 되었는지 확인하는 간격. 서버가 꺼져 있던 동안 놓친 백업은 켜자마자 만든다.
BACKUP_CHECK_SECONDS = 3600
logger = logging.getLogger(__name__)


class RedactOAuthCallback(logging.Filter):
    """Google이 주소에 붙여 보내는 승인 코드와 state를 접근 로그에서 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and args[2].startswith(GOOGLE_CALLBACK_PATH + "?"):
            record.args = (*args[:2], GOOGLE_CALLBACK_PATH + "?[생략]", *args[3:])
        return True


# uvicorn이 로그 설정을 마친 뒤 이 모듈을 불러오므로 여기서 붙인 필터가 유지된다.
logging.getLogger("uvicorn.access").addFilter(RedactOAuthCallback())


async def backup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(backup_service.run_scheduled, get_settings())
        except Exception:
            # 실패해도 서버는 계속 돌고, 오래된 백업은 지우지 않는다.
            logger.exception("자동 백업 실패")
        await asyncio.sleep(BACKUP_CHECK_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_schema(engine)
    with SessionLocal() as db:
        seed_all(db)
    backups = asyncio.create_task(backup_loop()) if get_settings().backup_enabled else None
    yield
    if backups:
        backups.cancel()


app = FastAPI(
    title="PawPath API",
    description="댕댕 산책각 - AI-Powered Personalized Pet Walking Recommendation",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    # 로그인 세션 쿠키를 주고받는다. 허용 출처를 명시해 두었으므로 안전하다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        return JSONResponse({"detail": "요청이 너무 커요."}, status_code=413)
    return await call_next(request)


app.include_router(api.router)

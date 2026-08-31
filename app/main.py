import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.main import api_router
from core import neo4j_client, postgres_client, setup_logging

# import 시점에 로깅을 먼저 구성해, lifespan 이전(앱 구동 초기)의 로그도 잡히게 한다.
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 두 DB 클라이언트를 열고(연결 확인 포함), 종료 시 역순으로 정리한다.
    logger.info("Starting FinnGraph AI Server")
    await neo4j_client.connect()
    await postgres_client.connect()
    yield
    await postgres_client.close()
    await neo4j_client.close()
    logger.info("Shutting down FinnGraph AI Server")


app = FastAPI(title="FinnGraph AI API Server", lifespan=lifespan)
app.include_router(api_router)

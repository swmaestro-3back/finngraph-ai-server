import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from api.main import api_router
from core import neo4j_database, postgres_client, setup_logging

# import 시점에 로깅을 먼저 구성해, lifespan 이전(앱 구동 초기)의 로그도 잡히게 한다.
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 Neo4j 드라이버·Postgres 풀 초기화, 종료 시 역순으로 커넥션 정리.
    logger.info("Starting FinnGraph AI Server")
    neo4j_database.init_driver()
    await postgres_client.connect()
    yield
    await postgres_client.close()
    await neo4j_database.close()
    logger.info("Shutting down FinnGraph AI Server")


app = FastAPI(title="FinnGraph AI API Server", lifespan=lifespan)


# ALB 타깃그룹 헬스체크 경로. Neo4j 가 응답하지 않으면 503 을 돌려 트래픽에서 빠진다.
@app.get("/health", include_in_schema=False)
async def health():
    try:
        await asyncio.wait_for(neo4j_database.execute("RETURN 1 AS ok"), timeout=5)
    except Exception:
        logger.warning("Neo4j health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "UP"}


app.include_router(api_router)

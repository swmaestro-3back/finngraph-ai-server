from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

from core.config import settings

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 30.0  # 기동 시 첫 커넥션을 기다리는 상한(초)


class PostgresClient:
    """ETL Postgres 커넥션 풀 싱글톤 — 수명주기는 lifespan 이 connect/close 로 잡는다."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        self._pool = AsyncConnectionPool(settings.database_url, open=False)
        # wait=True 로 첫 커넥션이 열릴 때까지 기다린다 —
        # DB 가 죽어 있으면 첫 요청이 아니라 기동에서 실패한다.
        await self._pool.open(wait=True, timeout=CONNECT_TIMEOUT)
        logger.info("Postgres pool opened")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Postgres pool closed")

    def connection(self):
        """`async with postgres_client.connection() as conn:` 로 쓴다."""
        if not self._pool:
            raise RuntimeError("Postgres client is not connected. Call connect first.")
        return self._pool.connection()


postgres_client = PostgresClient()

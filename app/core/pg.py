from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

from core.config import settings

logger = logging.getLogger(__name__)


class PostgresDatabase:
    """ETL Postgres 커넥션 풀 싱글톤. Neo4jDatabase 와 같은 수명주기(lifespan) 패턴."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        self._pool = AsyncConnectionPool(settings.database_url, open=False)
        await self._pool.open()
        logger.info("Postgres pool opened")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Postgres pool closed")

    def connection(self):
        """`async with postgres_database.connection() as conn:` 로 쓴다."""
        if not self._pool:
            raise RuntimeError("Postgres pool is not opened. Call open first.")
        return self._pool.connection()


postgres_database = PostgresDatabase()

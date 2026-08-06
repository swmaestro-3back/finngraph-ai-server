from __future__ import annotations

import logging
from typing import LiteralString

from neo4j import AsyncGraphDatabase, Record
from core import settings

logger = logging.getLogger(__name__)

class Neo4jDatabase:

    def __init__(self) -> None:
        self._driver = None

    def init_driver(self):
        self._driver = AsyncGraphDatabase.driver(
            uri=settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password)
        )
        logger.info(
            "Neo4j driver initialized (uri=%s, database=%s)",
            settings.neo4j_uri,
            settings.neo4j_database,
        )

    async def close(self):
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j driver closed")

    async def execute(self, query: LiteralString, parameters: dict | None = None) -> list[Record]:
        if not self._driver:
            raise RuntimeError("Neo4j Driver is not initialized. Call init_driver first.")

        logger.debug("Executing query with params=%s | %s", parameters, query)
        records, _, _ = await self._driver.execute_query(
            query, parameters_=parameters, database_=settings.neo4j_database
        )
        logger.debug("Query returned %d record(s)", len(records))

        # 원래 records, summary, keys 이렇게 3개 주는데 지금은 쿼리 결과인 records만
        # 사용하니 나머지는 버리는 용으로 _ 표기
        return records

# 전역적으로 하나의 객체만 사용
# 싱글톤 패턴 적용
neo4j_database = Neo4jDatabase()

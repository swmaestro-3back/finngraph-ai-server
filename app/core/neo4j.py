from __future__ import annotations

import logging
from typing import LiteralString

from neo4j import AsyncGraphDatabase, Record

from core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j 비동기 드라이버 싱글톤 — 수명주기는 lifespan 이 connect/close 로 잡는다."""

    def __init__(self) -> None:
        self._driver = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            uri=settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        # 드라이버 생성 자체는 접속하지 않는다(지연 연결) — 여기서 한 번 확인해
        # Neo4j 가 죽어 있으면 첫 요청이 아니라 기동 시점에 드러나게 한다.
        await self._driver.verify_connectivity()
        logger.info(
            "Neo4j connected (uri=%s, database=%s)",
            settings.neo4j_uri,
            settings.neo4j_database,
        )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j driver closed")

    async def execute(self, query: LiteralString, parameters: dict | None = None) -> list[Record]:
        if not self._driver:
            raise RuntimeError("Neo4j client is not connected. Call connect first.")

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
neo4j_client = Neo4jClient()

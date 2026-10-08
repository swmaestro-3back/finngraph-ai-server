"""테마 — 테마의 소속 기업, 기업의 소속 테마(BELONGS_TO)."""

from __future__ import annotations

from typing import LiteralString

from core import neo4j_database
from schemas import CompanyThemesResponse, ThemeResponse

from .mappers import to_company_themes_response, to_theme_response

# Theme 노드(embedding)와 BELONGS_TO 간선(reason_embedding)은 ai-server 내부용 임베딩을 갖고 있어
# 객체 대신 응답 필드만 맵으로 투영해 임베딩이 Neo4j 밖으로 나오지 않게 한다.
_THEME_QUERY: LiteralString = """
MATCH (t:Theme)
WHERE t.name = $key
CALL (t) {
  MATCH (c:Company)-[r:BELONGS_TO]->(t)
  RETURN collect(c) AS companies,
         collect({id: elementId(r), start: elementId(c), end: elementId(t), reason: r.reason}) AS relationships
}
RETURN t{.*, id: elementId(t), embedding: null} AS theme, companies, relationships
"""

# _THEME_QUERY 와 같은 이유로 Theme / BELONGS_TO 는 객체 대신 임베딩을 뺀 맵으로 투영한다.
_COMPANY_THEMES_QUERY: LiteralString = """
MATCH (c:Company)
WHERE c.ticker = $key
CALL (c) {
  MATCH (c)-[r:BELONGS_TO]->(t:Theme)
  RETURN collect(t{.*, id: elementId(t), embedding: null}) AS themes,
         collect({id: elementId(r), start: elementId(c), end: elementId(t), reason: r.reason}) AS relationships
}
RETURN c AS company, themes, relationships
"""


async def fetch_theme(name: str) -> ThemeResponse | None:
    records = await neo4j_database.execute(_THEME_QUERY, {"key": name})
    if not records:  # 해당 테마 자체가 없음
        return None
    return to_theme_response(records[0])


async def fetch_company_themes(ticker: str) -> CompanyThemesResponse | None:
    records = await neo4j_database.execute(_COMPANY_THEMES_QUERY, {"key": ticker})
    if not records:  # 기준 기업 자체가 없음
        return None
    return to_company_themes_response(records[0])

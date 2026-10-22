"""간선 근거 — 기업 간 간선이 가진 근거 기사 id·품목과 공시 접수번호."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, LiteralString

from core import neo4j_database

from .mappers import zip_mentions

# 그래프 응답이 준 간선 elementId 로 근거 목록만 꺼낸다 — 제목·날짜는 Postgres 가 갖고 있다.
_RELATIONSHIP_EVIDENCE_QUERY: LiteralString = """
MATCH (:Company)-[r:SUPPLIES_TO|ACQUIRES|INVESTS_IN]->(:Company)
WHERE elementId(r) = $id
RETURN r.news_ids AS news_ids, r.news_items AS news_items,
       r.disclosure_rcept_nos AS rcept_nos, r.disclosure_items AS disclosure_items
"""


@dataclass
class EvidenceRefs:
    """간선 하나의 근거 참조 — Postgres 에서 제목·날짜를 붙이기 전 상태."""

    items: dict[str, list[str]] = field(default_factory=dict)  # 기사 id → 품목 목록
    news_ids: list[int] = field(default_factory=list)  # news.id 와 맞출 수 있는 숫자 id 만
    disclosure_items: dict[str, str | None] = field(default_factory=dict)  # 접수번호 → 품목


def group_news_items(news_ids: list[Any], news_items: list[Any]) -> dict[str, list[str]]:
    """간선의 news_ids·news_items 를 기사별 품목 목록으로. 같은 기사가 품목만 달리 여러 번 실려 온다."""
    grouped: dict[str, list[str]] = {}
    for news_id, item in zip_mentions(news_ids, news_items):
        items = grouped.setdefault(news_id, [])
        if item and item not in items:
            items.append(item)
    return grouped


async def fetch_relationship_evidence(element_id: str) -> EvidenceRefs | None:
    """간선이 없으면 None."""
    records = await neo4j_database.execute(_RELATIONSHIP_EVIDENCE_QUERY, {"id": element_id})
    if not records:
        return None
    record = records[0]

    items = group_news_items(record["news_ids"] or [], record["news_items"] or [])
    # news_ids 는 적재 경로에 따라 문자열/정수가 섞인다 — 숫자가 아닌 id 는 news.id 와 맞출 수 없어 버린다.
    # isdigit() 은 '²' 같은 유니코드 숫자도 참이라 int() 가 터진다 — ASCII 십진수만 받는다
    news_ids = [int(news_id) for news_id in items if news_id.isascii() and news_id.isdecimal()]
    disclosure_items: dict[str, str | None] = {}
    for rcept_no, item in zip(record["rcept_nos"] or [], record["disclosure_items"] or []):
        disclosure_items.setdefault(str(rcept_no), item)
    for rcept_no in record["rcept_nos"] or []:
        disclosure_items.setdefault(str(rcept_no), None)

    return EvidenceRefs(items=items, news_ids=news_ids, disclosure_items=disclosure_items)

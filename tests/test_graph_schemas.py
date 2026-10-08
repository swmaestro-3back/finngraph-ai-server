"""노드 스키마 — Neo4j 프로퍼티 이름과 응답 필드가 맞물리는지, 채울 수 없는 필드가 빠졌는지 본다."""
from __future__ import annotations

from mappers import build_event, build_theme
from schemas import CompanyNode, StockQuote


class FakeNode:
    def __init__(self, element_id: str, labels: set[str], **props):
        self.element_id = element_id
        self.labels = frozenset(labels)
        self._props = props

    def keys(self):
        return self._props.keys()

    def __getitem__(self, key):
        return self._props[key]


def test_build_theme_keeps_etl_theme_id():
    theme = build_theme(
        {"id": "t1", "name": "2차전지", "description": None, "theme_id": 1, "embedding": None}
    )
    assert theme.theme_id == 1
    assert theme.quote is None


def test_build_event_keeps_only_fields_neo4j_or_postgres_can_fill():
    node = FakeNode(
        "e1", {"Event"}, cluster_id=7, title="수주", created_at="2026-10-01T00:00:00+09:00",
        first_published_at="2026-10-01T09:00:00+09:00", last_published_at="2026-10-02T09:00:00+09:00",
    )
    event = build_event(node)
    dumped = event.model_dump()
    assert event.cluster_id == 7
    assert event.keywords == [] and event.news_count is None
    for gone in ("news_ids", "companies", "member_count", "original_size", "titled_at", "synced_at"):
        assert gone not in dumped


def test_company_quote_defaults_to_none_and_serializes():
    company = CompanyNode(id="c1", ticker="005930")
    assert company.quote is None
    company.quote = StockQuote(
        price=263500.0, change=-1.86, market_cap=1540494253000000, price_date="2026-10-08"
    )
    assert company.model_dump()["quote"] == {
        "price": 263500.0, "change": -1.86, "market_cap": 1540494253000000,
        "r_1w": None, "r_1m": None, "r_3m": None, "price_date": "2026-10-08",
    }

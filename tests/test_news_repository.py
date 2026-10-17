"""repository.get_news_graph — neo4j_database.execute를 페이크로 바꿔 시드→확장→보강 오케스트레이션만 검증한다."""
from __future__ import annotations

import asyncio
from typing import Any

import repository


class FakeNode:
    """neo4j.graph.Node 흉내 — element_id, labels, 그리고 dict(node)가 되는 매핑."""

    def __init__(self, element_id: str, **props):
        self.element_id = element_id
        self.labels = frozenset({"Company"})
        self._props = {"ticker": element_id, "name": f"기업{element_id}", **props}

    def keys(self):
        return self._props.keys()

    def __getitem__(self, key):
        return self._props[key]


class FakeRel:
    def __init__(self, element_id: str, start: FakeNode, end: FakeNode, mentions: int = 1):
        self.element_id = element_id
        self.type = "SUPPLIES_TO"
        self.start_node = start
        self.end_node = end
        self._props = {"news_ids": ["10"], "news_items": ["품목"], "news_mention_count": mentions}

    def keys(self):
        return self._props.keys()

    def __getitem__(self, key):
        return self._props[key]


A, B, C, D = (FakeNode(x) for x in "ABCD")


class FakeExecutor:
    """호출을 (query, params) 순서로 기록하고, 미리 정해둔 응답을 순서대로 돌려준다."""

    def __init__(self, responses: list[list[dict[str, Any]]]):
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append((query, params))
        return self._responses[len(self.calls) - 1]

    def query_kind(self, index: int) -> str:
        query = self.calls[index][0]
        if "UNWIND $frontier" in query:
            return "expand"
        if "elementId(a) IN $ids" in query:
            return "closure"
        return "seed"


def test_hop1_only_runs_seed_query(monkeypatch):
    fake = FakeExecutor([[{"a": A, "r": FakeRel("r1", A, B), "b": B}]])
    monkeypatch.setattr(repository.neo4j_database, "execute", fake.execute)

    res = asyncio.run(repository.get_news_graph("10", hop=1))

    assert len(fake.calls) == 1
    assert fake.query_kind(0) == "seed"
    assert fake.calls[0][1] == {"news_id": "10"}
    assert res is not None
    assert res.seed_relationship_ids == ["r1"]
    assert res.truncated is False


def test_hop3_expands_twice_then_closes(monkeypatch):
    fake = FakeExecutor(
        [
            [{"a": A, "r": FakeRel("r1", A, B), "b": B}],  # seed
            [{"r": FakeRel("r2", A, C), "m": C}],  # expand 1: A -> C
            [{"r": FakeRel("r3", C, D), "m": D}],  # expand 2: C -> D
            [{"r": FakeRel("r4", B, D)}],  # closure: extra relation among gathered companies
        ]
    )
    monkeypatch.setattr(repository.neo4j_database, "execute", fake.execute)

    res = asyncio.run(repository.get_news_graph("10", hop=3))

    assert len(fake.calls) == 4
    assert fake.query_kind(0) == "seed"

    assert fake.query_kind(1) == "expand"
    assert fake.calls[1][1] == {
        "frontier": ["A", "B"],
        "per_node": repository.NEWS_EXPAND_PER_NODE,
    }

    assert fake.query_kind(2) == "expand"
    assert fake.calls[2][1] == {
        "frontier": ["C"],
        "per_node": repository.NEWS_EXPAND_PER_NODE,
    }

    assert fake.query_kind(3) == "closure"
    assert fake.calls[3][1] == {"ids": ["A", "B", "C", "D"]}

    assert res is not None
    assert [c.id for c in res.companies] == ["A", "B", "C", "D"]
    assert "r4" in [r.id for r in res.relationships]


def test_no_seeds_returns_none_without_further_calls(monkeypatch):
    fake = FakeExecutor([[]])
    monkeypatch.setattr(repository.neo4j_database, "execute", fake.execute)

    res = asyncio.run(repository.get_news_graph("10", hop=3))

    assert res is None
    assert len(fake.calls) == 1


def test_hop3_stops_expanding_once_cap_hit(monkeypatch):
    monkeypatch.setattr(repository, "NEWS_MAX_NODES", 3)
    fake = FakeExecutor(
        [
            [{"a": A, "r": FakeRel("r1", A, B), "b": B}],  # seed: A, B (len=2)
            [
                {"r": FakeRel("r2", A, C), "m": C},  # len 2 -> 3, still under cap, added
                {"r": FakeRel("r3", A, D), "m": D},  # len already at cap, dropped, truncated=True
            ],
            [{"r": FakeRel("r4", B, C)}],  # closure
        ]
    )
    monkeypatch.setattr(repository.neo4j_database, "execute", fake.execute)

    res = asyncio.run(repository.get_news_graph("10", hop=3))

    assert len(fake.calls) == 3
    assert fake.query_kind(0) == "seed"
    assert fake.query_kind(1) == "expand"
    assert fake.query_kind(2) == "closure"

    assert res is not None
    assert res.truncated is True
    assert [c.id for c in res.companies] == ["A", "B", "C"]
    assert fake.calls[2][1] == {"ids": ["A", "B", "C"]}

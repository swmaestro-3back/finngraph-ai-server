"""NewsGraphAccumulator — Neo4j 없이 dict 레코드와 가짜 노드/관계로 검증한다."""
from __future__ import annotations

from news_graph import NewsGraphAccumulator


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


A, B, C, D, E = (FakeNode(x) for x in "ABCDE")


def test_seeds_register_companies_and_relationships_as_seed():
    acc = NewsGraphAccumulator(max_nodes=60)
    acc.add_seeds([{"a": A, "r": FakeRel("r1", A, B), "b": B}, {"a": B, "r": FakeRel("r2", B, C), "b": C}])

    res = acc.to_response()
    assert [c.id for c in res.companies] == ["A", "B", "C"]
    assert res.seed_company_ids == ["A", "B", "C"]
    assert res.seed_relationship_ids == ["r1", "r2"]
    assert [r.id for r in res.relationships] == ["r1", "r2"]
    assert res.relationships[0].news[0].news_id == "10"
    assert res.relationships[0].news[0].item == "품목"
    assert res.truncated is False


def test_expansion_returns_new_frontier_and_skips_known_nodes():
    acc = NewsGraphAccumulator(max_nodes=60)
    acc.add_seeds([{"a": A, "r": FakeRel("r1", A, B), "b": B}])

    frontier = acc.add_expansion([
        {"r": FakeRel("r3", A, C), "m": C},
        {"r": FakeRel("r1", A, B), "m": B},  # 이미 있는 기업·관계는 다시 담지 않는다
        {"r": FakeRel("r4", B, D), "m": D},
    ])

    assert frontier == ["C", "D"]
    res = acc.to_response()
    assert [c.id for c in res.companies] == ["A", "B", "C", "D"]
    assert [r.id for r in res.relationships] == ["r1", "r3", "r4"]
    # 확장으로 온 것은 시드가 아니다
    assert res.seed_relationship_ids == ["r1"]
    assert res.seed_company_ids == ["A", "B"]


def test_expansion_stops_at_max_nodes_and_flags_truncated():
    acc = NewsGraphAccumulator(max_nodes=3)
    acc.add_seeds([{"a": A, "r": FakeRel("r1", A, B), "b": B}])

    frontier = acc.add_expansion([
        {"r": FakeRel("r3", A, C), "m": C},
        {"r": FakeRel("r4", A, D), "m": D},  # 상한 초과 — 노드도 간선도 버린다
        {"r": FakeRel("r5", B, A), "m": A},  # 이미 있는 기업 사이 간선은 상한과 무관하게 담는다
    ])

    assert frontier == ["C"]
    res = acc.to_response()
    assert [c.id for c in res.companies] == ["A", "B", "C"]
    assert [r.id for r in res.relationships] == ["r1", "r3", "r5"]
    assert res.truncated is True


def test_closure_adds_relationships_only():
    acc = NewsGraphAccumulator(max_nodes=60)
    acc.add_seeds([{"a": A, "r": FakeRel("r1", A, B), "b": B}])
    acc.add_expansion([{"r": FakeRel("r3", A, C), "m": C}])

    acc.add_closure([{"r": FakeRel("r6", B, C)}, {"r": FakeRel("r1", A, B)}])

    res = acc.to_response()
    assert [c.id for c in res.companies] == ["A", "B", "C"]
    assert [r.id for r in res.relationships] == ["r1", "r3", "r6"]

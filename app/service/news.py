from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from repository import neo4j
from repository.neo4j.mappers import build_company, build_supply
from schemas import CompanyNode, NewsGraphResponse, SupplyRelationship

# 확장 상한 — 기업당 이웃 수와 전체 노드 수. 모달의 420px 캔버스에서 읽히는 크기에 맞춘다.
NEWS_EXPAND_PER_NODE = 8
NEWS_MAX_NODES = 60


@dataclass
class NewsGraphAccumulator:
    """뉴스 그래프를 시드 → 확장 → 보강 순서로 쌓는다.

    Neo4j 레코드를 받지만 DB에는 손대지 않아 dict 레코드로도 검증할 수 있다.
    노드 상한(max_nodes)은 확장 단계에서만 검사한다 — 시드는 뉴스에서 온 것이라 전부 담는다.
    """

    max_nodes: int
    companies: dict[str, CompanyNode] = field(default_factory=dict)
    relationships: dict[str, SupplyRelationship] = field(default_factory=dict)
    seed_relationship_ids: list[str] = field(default_factory=list)
    seed_company_ids: list[str] = field(default_factory=list)
    truncated: bool = False

    def add_seeds(self, records: Iterable[Mapping[str, Any]]) -> None:
        """`RETURN a, r, b` — 이 뉴스를 근거로 가진 관계. 양끝 기업이 시드 기업이 된다."""
        for record in records:
            for node in (record["a"], record["b"]):
                if node.element_id not in self.companies:
                    self.companies[node.element_id] = build_company(node)
                    self.seed_company_ids.append(node.element_id)
            rel = record["r"]
            if rel.element_id not in self.relationships:
                self.relationships[rel.element_id] = build_supply(rel)
                self.seed_relationship_ids.append(rel.element_id)

    def add_expansion(self, records: Iterable[Mapping[str, Any]]) -> list[str]:
        """`RETURN r, m` — 프론티어 기업의 이웃 m과 그 간선. 새로 들어온 기업 id(다음 프론티어)를 돌려준다.

        상한에 닿으면 남은 새 기업은 간선째 버리고 truncated를 켠다 — 한쪽 끝이 없는 간선을 남기지 않는다.
        이미 담긴 기업 사이의 간선은 노드가 늘지 않으므로 상한과 무관하게 담는다.
        """
        added: list[str] = []
        for record in records:
            rel, node = record["r"], record["m"]
            if node.element_id not in self.companies:
                if len(self.companies) >= self.max_nodes:
                    self.truncated = True
                    continue
                self.companies[node.element_id] = build_company(node)
                added.append(node.element_id)
            if rel.element_id not in self.relationships:
                self.relationships[rel.element_id] = build_supply(rel)
        return added

    def add_closure(self, records: Iterable[Mapping[str, Any]]) -> None:
        """`RETURN r` — 담긴 기업들 사이의 관계 전부. 노드는 늘지 않는다."""
        for record in records:
            rel = record["r"]
            if rel.element_id not in self.relationships:
                self.relationships[rel.element_id] = build_supply(rel)

    def to_response(self) -> NewsGraphResponse:
        return NewsGraphResponse(
            companies=list(self.companies.values()),
            relationships=list(self.relationships.values()),
            seed_relationship_ids=list(self.seed_relationship_ids),
            seed_company_ids=list(self.seed_company_ids),
            truncated=self.truncated,
        )


async def get_news_graph(news_id: str, hop: int = 1) -> NewsGraphResponse | None:
    """뉴스 시드 관계에서 시작해 hop-1 단계만큼 기업 간 관계를 따라 펼친다.

    시드 0건이면 None(404). hop ≥ 2 면 단계마다 프론티어 기업의 상위 이웃을 붙이고,
    마지막에 담긴 기업들 사이의 관계를 보강해 연결이 빠지지 않게 한다.
    """
    seeds = await neo4j.fetch_news_seeds(news_id)
    if not seeds:  # 이 뉴스를 근거로 가진 관계가 없음
        return None

    acc = NewsGraphAccumulator(max_nodes=NEWS_MAX_NODES)
    acc.add_seeds(seeds)

    frontier = list(acc.seed_company_ids)
    for _ in range(hop - 1):
        if not frontier or acc.truncated:
            break
        records = await neo4j.fetch_news_expansion(frontier, NEWS_EXPAND_PER_NODE)
        frontier = acc.add_expansion(records)

    if hop > 1:
        records = await neo4j.fetch_news_closure(list(acc.companies))
        acc.add_closure(records)

    return acc.to_response()

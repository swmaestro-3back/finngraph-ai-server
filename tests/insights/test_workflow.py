"""LangGraph 워크플로우 토폴로지 테스트.

supply_chain 단일 에이전트:
START → collect_supply → (후보 없으면 END) → supply_judge → END.
실행 계약(강등·에러)은 서비스 통합 테스트가 검증한다.
"""

from __future__ import annotations

from langgraph.graph import END

from graph.workflow import insight_graph, route_after_collect_supply


def test_graph_topology():
    drawable = insight_graph.get_graph()
    assert {"collect_supply", "supply_judge"} <= set(drawable.nodes)
    from_start = {edge.target for edge in drawable.edges if edge.source == "__start__"}
    assert from_start == {"collect_supply"}


def test_collect_supply_routes_to_end_without_candidates():
    assert route_after_collect_supply({"candidates": []}) == END
    assert route_after_collect_supply({}) == END
    assert route_after_collect_supply({"candidates": [object()]}) == "supply_judge"

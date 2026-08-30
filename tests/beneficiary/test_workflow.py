"""토폴로지·라우팅 테스트 — 조건부 엣지는 순수 라우팅만 한다 (상태 변경 금지)."""

from __future__ import annotations

from langgraph.graph import END

from beneficiary.models import NewsPlan, RivalProbe
from beneficiary.workflow import (
    beneficiary_graph,
    route_after_analyze,
    route_after_enrich,
    route_after_expand_rivals,
    route_after_expand_supply,
    route_after_select,
)

POSITIVE = NewsPlan(event_summary="s", polarity="positive", core_items=["HBM"])
NEGATIVE = NewsPlan(event_summary="s", polarity="negative", core_items=["HBM"],
                    rival_probes=[RivalProbe(subject_name="루트 기업", themes=["테마A"])])
NEGATIVE_NO_PROBE = NewsPlan(event_summary="s", polarity="negative")


def test_graph_topology_has_eight_nodes_and_starts_at_analyze():
    drawable = beneficiary_graph.get_graph()
    assert {"analyze_news", "expand_supply", "filter_supply", "expand_rivals",
            "filter_rivals", "select_candidates", "enrich", "judge"} <= set(drawable.nodes)
    from_start = {edge.target for edge in drawable.edges if edge.source == "__start__"}
    assert from_start == {"analyze_news"}


def test_route_after_analyze_polarity_split_and_early_exits():
    root_companies = [object()]
    assert route_after_analyze({"error": "boom", "root_companies": root_companies, "plan": POSITIVE}) == END
    assert route_after_analyze({"root_companies": [], "plan": None}) == END
    assert route_after_analyze({"root_companies": root_companies, "plan": POSITIVE}) == "expand_supply"
    assert route_after_analyze({"root_companies": root_companies, "plan": NEGATIVE}) == "expand_rivals"
    # negative 인데 유효 probe 0 → expand_rivals 를 실행하지 않고 즉시 END
    assert route_after_analyze({"root_companies": root_companies, "plan": NEGATIVE_NO_PROBE}) == END


def test_route_after_expand_nodes():
    assert route_after_expand_supply({"error": "x", "edges": [object()]}) == END
    assert route_after_expand_supply({"edges": []}) == END
    assert route_after_expand_supply({"edges": [object()]}) == "filter_supply"
    assert route_after_expand_rivals({"rivals": []}) == END
    assert route_after_expand_rivals({"rivals": [object()]}) == "filter_rivals"


def test_route_after_select_and_enrich():
    assert route_after_select({"candidates": []}) == END
    assert route_after_select({"candidates": [object()]}) == "enrich"
    assert route_after_enrich({"candidates": []}) == END  # affirmed 0건 전멸
    assert route_after_enrich({"error": "x", "candidates": [object()]}) == END
    assert route_after_enrich({"candidates": [object()]}) == "judge"

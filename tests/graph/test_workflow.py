"""토폴로지·라우팅 테스트 — 조건부 엣지는 순수 라우팅만 한다 (상태 변경 금지)."""

from __future__ import annotations

from langgraph.graph import END

from graph.models import NewsPlan, RivalProbe
from graph.subgraph import build_supply_chain_subgraph, build_theme_subgraph
from graph.subgraph.supply_chain.graph import route_after_expand_supply
from graph.subgraph.theme.graph import route_after_expand_rivals
from graph.workflow import (
    beneficiary_graph,
    route_after_analyze,
    route_after_enrich,
    route_after_select,
    route_after_track,
)

POSITIVE = NewsPlan(event_summary="s", polarity="positive", core_items=["HBM"])
NEGATIVE = NewsPlan(event_summary="s", polarity="negative", core_items=["HBM"],
                    rival_probes=[RivalProbe(subject_name="루트 기업", themes=["테마A"])])
NEGATIVE_NO_PROBE = NewsPlan(event_summary="s", polarity="negative")


def test_parent_topology_has_subgraph_nodes_and_starts_at_analyze():
    drawable = beneficiary_graph.get_graph()
    assert {"analyze_news", "supply_chain_subgraph", "theme_subgraph",
            "select_candidates", "enrich", "judge"} <= set(drawable.nodes)
    # expand/filter 는 서브그래프 내부라 부모 그래프에는 노출되지 않는다
    assert not {"expand_supply", "filter_supply", "expand_rivals", "filter_rivals"} & set(drawable.nodes)
    from_start = {edge.target for edge in drawable.edges if edge.source == "__start__"}
    assert from_start == {"analyze_news"}


def test_subgraph_topologies_are_expand_then_filter():
    supply = build_supply_chain_subgraph().get_graph()
    assert {"expand_supply", "filter_supply"} <= set(supply.nodes)
    theme = build_theme_subgraph().get_graph()
    assert {"expand_rivals", "filter_rivals"} <= set(theme.nodes)


def test_route_after_analyze_polarity_split_and_early_exits():
    root_companies = [object()]
    assert route_after_analyze({"error": "boom", "root_companies": root_companies, "plan": POSITIVE}) == END
    assert route_after_analyze({"root_companies": [], "plan": None}) == END
    assert route_after_analyze({"root_companies": root_companies, "plan": POSITIVE}) == "supply_chain_subgraph"
    assert route_after_analyze({"root_companies": root_companies, "plan": NEGATIVE}) == "theme_subgraph"
    # negative 인데 유효 probe 0 → theme_subgraph 를 실행하지 않고 즉시 END
    assert route_after_analyze({"root_companies": root_companies, "plan": NEGATIVE_NO_PROBE}) == END


def test_route_after_expand_nodes_inside_subgraphs():
    assert route_after_expand_supply({"error": "x", "edges": [object()]}) == END
    assert route_after_expand_supply({"edges": []}) == END
    assert route_after_expand_supply({"edges": [object()]}) == "filter_supply"
    assert route_after_expand_rivals({"rivals": []}) == END
    assert route_after_expand_rivals({"rivals": [object()]}) == "filter_rivals"


def test_route_after_track_promotes_subgraph_early_exit_to_global_end():
    # 서브그래프 내부 END 는 부모로 복귀하므로 error/풀 0 은 여기서 전체 END 로 승격
    assert route_after_track({"error": "x", "edges": [object()]}) == END
    assert route_after_track({"edges": [], "rivals": []}) == END
    assert route_after_track({}) == END
    assert route_after_track({"edges": [object()]}) == "select_candidates"
    assert route_after_track({"rivals": [object()]}) == "select_candidates"


def test_route_after_select_and_enrich():
    assert route_after_select({"candidates": []}) == END
    assert route_after_select({"candidates": [object()]}) == "enrich"
    assert route_after_enrich({"candidates": []}) == END  # affirmed 0건 전멸
    assert route_after_enrich({"error": "x", "candidates": [object()]}) == END
    assert route_after_enrich({"candidates": [object()]}) == "judge"

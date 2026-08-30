"""beneficiary compiled graph 조립 — 극성별 서브그래프 2개 + 공통 후반부.

START → analyze_news ──(error/루트 기업 없음/negative&probe 0)──→ END
   ├─(positive)→ [supply_chain_subgraph: expand_supply → filter_supply] ─┐
   └─(negative)→ [theme_subgraph:        expand_rivals → filter_rivals] ─┤
                                                        (error/풀 0→END) ▼
   select_candidates ─(error/후보0)→END → enrich ─(error/전멸)→END → judge → END

서브그래프 내부의 END 는 서브그래프 종료일 뿐이다(제어는 부모로 복귀) —
전체 조기 종료는 서브그래프-직후 라우터 route_after_track 이 다시 판정한다.
조건부 엣지는 순수 라우팅만 한다(상태 변경 금지). 모든 라우터는 error 를
최우선 검사한다. 분기는 if/else 지 병렬이 아니다 — 조인 배리어·리듀서 불필요.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.nodes import analyze_news, enrich, judge, select_candidates
from graph.state import GraphState
from graph.subgraph import build_supply_chain_subgraph, build_theme_subgraph


def route_after_analyze(state: GraphState) -> str:
    if state.get("error"):
        return END
    plan = state.get("plan")
    if not state.get("root_companies") or plan is None:
        return END
    if plan.polarity == "negative":
        return "theme_subgraph" if plan.rival_probes else END
    return "supply_chain_subgraph"


def route_after_track(state: GraphState) -> str:
    """서브그래프 복귀 지점 — 내부 조기 종료(error/풀 0)를 전체 종료로 승격한다."""
    if state.get("error"):
        return END
    if not state.get("edges") and not state.get("rivals"):
        return END
    return "select_candidates"


def route_after_select(state: GraphState) -> str:
    if state.get("error") or not state.get("candidates"):
        return END
    return "enrich"


def route_after_enrich(state: GraphState) -> str:
    if state.get("error") or not state.get("candidates"):
        return END
    return "judge"


def build_beneficiary_graph():
    builder = StateGraph(GraphState)
    builder.add_node("analyze_news", analyze_news)
    builder.add_node("supply_chain_subgraph", build_supply_chain_subgraph())
    builder.add_node("theme_subgraph", build_theme_subgraph())
    builder.add_node("select_candidates", select_candidates)
    builder.add_node("enrich", enrich)
    builder.add_node("judge", judge)

    builder.add_edge(START, "analyze_news")
    builder.add_conditional_edges(
        "analyze_news", route_after_analyze,
        ["supply_chain_subgraph", "theme_subgraph", END],
    )
    builder.add_conditional_edges(
        "supply_chain_subgraph", route_after_track, ["select_candidates", END]
    )
    builder.add_conditional_edges(
        "theme_subgraph", route_after_track, ["select_candidates", END]
    )
    builder.add_conditional_edges(
        "select_candidates", route_after_select, ["enrich", END]
    )
    builder.add_conditional_edges("enrich", route_after_enrich, ["judge", END])
    builder.add_edge("judge", END)
    return builder.compile()


beneficiary_graph = build_beneficiary_graph()

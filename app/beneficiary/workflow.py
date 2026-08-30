"""beneficiary compiled graph 조립 — 루프 없는 DAG + 극성 조건 분기 1개.

START → analyze_news ──(error/루트 기업 없음/negative&probe 0)──→ END
   ├─(positive)→ expand_supply ─(error/간선0)→END → filter_supply ─┐
   └─(negative)→ expand_rivals ─(error/후보0)→END → filter_rivals ─┤
                                                                   ▼
   select_candidates ─(error/후보0)→END → enrich ─(error/전멸)→END → judge → END

조건부 엣지는 순수 라우팅만 한다(상태 변경 금지). 모든 라우터는 error 를
최우선 검사한다. 분기는 if/else 지 병렬이 아니다 — 조인 배리어·리듀서 불필요.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from beneficiary.nodes import (
    analyze_news,
    enrich,
    expand_rivals,
    expand_supply,
    filter_rivals,
    filter_supply,
    judge,
    select_candidates,
)
from beneficiary.state import GraphState


def route_after_analyze(state: GraphState) -> str:
    if state.get("error"):
        return END
    plan = state.get("plan")
    if not state.get("root_companies") or plan is None:
        return END
    if plan.polarity == "negative":
        return "expand_rivals" if plan.rival_probes else END
    return "expand_supply"


def route_after_expand_supply(state: GraphState) -> str:
    if state.get("error") or not state.get("edges"):
        return END
    return "filter_supply"


def route_after_expand_rivals(state: GraphState) -> str:
    if state.get("error") or not state.get("rivals"):
        return END
    return "filter_rivals"


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
    builder.add_node("expand_supply", expand_supply)
    builder.add_node("filter_supply", filter_supply)
    builder.add_node("expand_rivals", expand_rivals)
    builder.add_node("filter_rivals", filter_rivals)
    builder.add_node("select_candidates", select_candidates)
    builder.add_node("enrich", enrich)
    builder.add_node("judge", judge)

    builder.add_edge(START, "analyze_news")
    builder.add_conditional_edges(
        "analyze_news", route_after_analyze, ["expand_supply", "expand_rivals", END]
    )
    builder.add_conditional_edges(
        "expand_supply", route_after_expand_supply, ["filter_supply", END]
    )
    builder.add_conditional_edges(
        "expand_rivals", route_after_expand_rivals, ["filter_rivals", END]
    )
    builder.add_edge("filter_supply", "select_candidates")
    builder.add_edge("filter_rivals", "select_candidates")
    builder.add_conditional_edges(
        "select_candidates", route_after_select, ["enrich", END]
    )
    builder.add_conditional_edges("enrich", route_after_enrich, ["judge", END])
    builder.add_edge("judge", END)
    return builder.compile()


beneficiary_graph = build_beneficiary_graph()

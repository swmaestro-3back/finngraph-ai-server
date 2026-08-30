"""공급망 서브그래프 조립 — START → expand_supply ─(error/간선0→END)→ filter_supply → END.

여기서의 END 는 서브그래프의 끝일 뿐이다 — 제어는 부모 workflow 로 복귀하며,
전체 실행의 조기 종료(error/풀 0)는 부모의 route_after_track 이 다시 판정한다.
라우터는 순수 라우팅만 하고 error 를 최우선 검사한다(스펙 §9).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import GraphState
from graph.subgraph.supply_chain.nodes import expand_supply, filter_supply


def route_after_expand_supply(state: GraphState) -> str:
    if state.get("error") or not state.get("edges"):
        return END
    return "filter_supply"


def build_supply_chain_subgraph():
    builder = StateGraph(GraphState)
    builder.add_node("expand_supply", expand_supply)
    builder.add_node("filter_supply", filter_supply)
    builder.add_edge(START, "expand_supply")
    builder.add_conditional_edges(
        "expand_supply", route_after_expand_supply, ["filter_supply", END]
    )
    builder.add_edge("filter_supply", END)
    return builder.compile()

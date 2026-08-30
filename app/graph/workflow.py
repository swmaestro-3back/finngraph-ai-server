"""compiled graph 조립 — supply_chain 단일 에이전트.

    START → collect_supply ─(후보 없으면 END)→ supply_judge → END

- collect_supply: 뉴스 관계의 object company 를 ticker 로 특정해 Neo4j 에서
  SUPPLIES_TO 1-hop 이웃을 찾고(subject ticker 기업 제외), disclosure_count
  상위 3개로 압축한 뒤 근거·연간 재무 테이블을 적재한다 (LLM 없음).
- supply_judge: 재무 5단계 체크리스트로 후보를 심사·랭킹한다 (LLM).
- 재시도는 llm 계층의 with_retry 가 담당한다. 노드는 예외를 직접 잡아
  error 키로 강등하므로 노드 밖으로 예외가 나가지 않는다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.nodes import collect_supply, supply_judge
from graph.state import GraphState


def route_after_collect_supply(state: GraphState) -> str:
    if not state.get("candidates"):
        return END
    return "supply_judge"


def build_insight_graph():
    builder = StateGraph(GraphState)
    builder.add_node("collect_supply", collect_supply)
    builder.add_node("supply_judge", supply_judge)

    builder.add_edge(START, "collect_supply")
    builder.add_conditional_edges(
        "collect_supply", route_after_collect_supply, ["supply_judge", END]
    )
    builder.add_edge("supply_judge", END)
    return builder.compile()


insight_graph = build_insight_graph()

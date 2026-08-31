"""토폴로지·라우팅·실패 강등 테스트.

조건부 엣지는 순수 라우팅만 한다(상태 변경 금지). 예외 → error 강등은 노드가
아니라 여기 등록된 error_handler 가 한다(스펙 §9).
"""

from __future__ import annotations

from langgraph.errors import NodeError
from langgraph.graph import END

from beneficiary.agent.workflow import (
    beneficiary_graph,
    demote_to_error,
    stop_or,
)


def test_topology_is_flat_and_starts_at_planner():
    drawable = beneficiary_graph.get_graph()
    assert {"planner", "expand_supply", "filter_supply",
            "candidate_selector", "finance_collector", "evaluator"} == {
        n for n in drawable.nodes if not n.startswith("__")
    }
    from_start = {edge.target for edge in drawable.edges if edge.source == "__start__"}
    assert from_start == {"planner"}


def test_every_node_can_exit_early():
    # 정지 신호는 어느 노드에서든 END 로 나갈 수 있어야 한다 (evaluator 는 종점).
    targets = {edge.source for edge in beneficiary_graph.get_graph().edges
               if edge.target == "__end__"}
    assert {"planner", "expand_supply", "filter_supply",
            "candidate_selector", "finance_collector", "evaluator"} <= targets


def test_stop_or_passes_through_only_when_not_stopped():
    route = stop_or("candidate_selector")
    assert route({"edges": [object()]}) == "candidate_selector"
    assert route({"error": "x"}) == END
    assert route({"status": "no_candidates"}) == END


def test_every_node_registers_an_error_handler():
    # 예외는 그래프 밖으로 나가지 않는다 — 노드 하나라도 빠지면 500 이 샌다.
    nodes = beneficiary_graph.nodes
    for name in ("planner", "expand_supply", "filter_supply",
                 "candidate_selector", "finance_collector", "evaluator"):
        assert nodes[name].error_handler_node, f"{name} 에 error_handler 가 없다"


def test_demote_to_error_writes_error_and_fallback_keys():
    handler = demote_to_error({"edges": []})
    command = handler({}, NodeError(node="expand_supply", error=RuntimeError("neo4j down")))
    assert command.update == {"edges": [], "error": "neo4j down"}
    # 강등된 상태를 그 노드의 라우터에 물리면 END 로 나간다 (폴백 없음).
    assert stop_or("filter_supply")(command.update) == END


def test_demote_to_error_fallback_can_read_state():
    handler = demote_to_error(lambda state: {"pool_size": len(state.get("candidates", []))})
    command = handler({"candidates": [object(), object()]},
                      NodeError(node="evaluator", error=RuntimeError("bedrock down")))
    assert command.update == {"pool_size": 2, "error": "bedrock down"}

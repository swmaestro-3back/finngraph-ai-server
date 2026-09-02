"""토폴로지·라우팅·부분 실패·실패 강등 테스트.

토폴로지의 핵심은 하나다 — planner 가 두 트랙으로 팬아웃하고, 두 트랙은
END 로 가지 않고 candidate_selector 한 곳으로 수렴한다. 한쪽 트랙이 빈손이든
장애든 다른 쪽 결과를 버리지 않는다는 뜻이다(스펙 §3).

조건부 엣지는 순수 라우팅만 한다(상태 변경 금지). 예외 → error 강등은 노드가
아니라 여기 등록된 error_handler 가 한다(스펙 §9).
"""

from __future__ import annotations

import asyncio

from langgraph.errors import NodeError
from langgraph.graph import END

from beneficiary.models import (
    NewsContext,
    NewsPlan,
    ScenarioProbe,
    SubgraphResult,
    SupplySubgraphResult,
    ThemeSubgraphResult,
)
from beneficiary.agent import workflow
from beneficiary.agent.workflow import (
    beneficiary_graph,
    demote_to_error,
    route_after_plan,
    stop_or,
    theme_track,
)

POSITIVE = NewsPlan(event_summary="s", polarity="positive", core_items=["변압기"],
                    scenario_probes=[ScenarioProbe(stage=1, hypothesis="h", query="q")])
NO_PROBES = NewsPlan(event_summary="s", polarity="positive", core_items=["변압기"])
NEWS = NewsContext(title="t", summary="s", published_at="2026-09-01", link=None)


# --- 토폴로지 -------------------------------------------------------------

def test_topology_has_two_parallel_tracks():
    """theme_track 노드가 빠지면(= 단일 트랙 그래프면) 실패한다."""
    nodes = {n for n in beneficiary_graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {"planner", "supply_track", "theme_track",
                     "candidate_selector", "finance_collector", "evaluator"}


def test_graph_starts_at_planner():
    from_start = {e.target for e in beneficiary_graph.get_graph().edges
                  if e.source == "__start__"}
    assert from_start == {"planner"}


def test_planner_fans_out_to_both_tracks():
    """planner 가 한 트랙 이름만 반환하면(팬아웃 아님) 실패한다."""
    assert set(route_after_plan({"plan": POSITIVE})) == {"supply_track", "theme_track"}


def test_planner_stop_signal_ends_without_running_tracks():
    assert route_after_plan({"plan": None, "status": "not_positive"}) == END


def test_tracks_never_route_to_end():
    """트랙은 빈손이든 장애든 팬인까지 간다 — 종료 판정은 selector 한 곳이다.

    트랙에 stop_or 조건부 엣지를 달면(한쪽 트랙의 장애가 다른 쪽 결과를
    버리는 옛 구조) END 타깃이 생겨 실패한다.
    """
    edges = beneficiary_graph.get_graph().edges
    for track in ("supply_track", "theme_track"):
        targets = {e.target for e in edges if e.source == track}
        assert targets == {"candidate_selector"}, f"{track} 이 END 로 나간다"


def test_selector_is_the_fan_in_point():
    """트랙 하나만 selector 로 들어오거나 트랙이 직렬로 이어지면 실패한다."""
    sources = {e.source for e in beneficiary_graph.get_graph().edges
               if e.target == "candidate_selector"}
    assert sources == {"supply_track", "theme_track"}


def test_only_selector_and_later_nodes_can_end_early():
    """조기 종료는 planner 와 팬인 이후에만 있다 — 트랙에는 없다."""
    targets = {e.source for e in beneficiary_graph.get_graph().edges
               if e.target == "__end__"}
    assert targets == {"planner", "candidate_selector", "finance_collector", "evaluator"}


# --- 팬아웃/팬인 실행 -----------------------------------------------------

def _fake_graph(monkeypatch, on_supply, on_theme, selector_seen):
    """트랙·planner·selector 를 가짜로 바꿔 토폴로지만 실행해 본다."""

    async def _plan(state):
        return {"news": NEWS, "plan": POSITIVE,
                "root_companies": [], "relation_lines": []}

    async def _select(state):
        supply = state.get("supply_result") or SupplySubgraphResult()
        theme = state.get("theme_result") or ThemeSubgraphResult()
        selector_seen.append({"edges": list(supply.edges), "hits": list(theme.hits)})
        return {"candidates": [], "status": "no_candidates"}

    monkeypatch.setattr(workflow, "build_plan", _plan)
    monkeypatch.setattr(workflow, "supply_track", on_supply)
    monkeypatch.setattr(workflow, "theme_track", on_theme)
    monkeypatch.setattr(workflow, "select_candidates", _select)
    return workflow.build_beneficiary_graph()


async def test_fan_in_runs_once_with_both_tracks_results(monkeypatch):
    """팬인이 두 트랙 결과를 모두 들고 정확히 한 번 돈다.

    한 트랙 쓰기가 유실되거나 selector 가 트랙마다 한 번씩(총 2회) 돌면 실패한다.
    """

    async def _supply(state):
        return {"supply_result": SupplySubgraphResult(edges=["e1"])}

    async def _theme(state):
        return {"theme_result": ThemeSubgraphResult(hits=["t1"])}

    seen: list[dict] = []
    graph = _fake_graph(monkeypatch, _supply, _theme, seen)
    await graph.ainvoke({"rep_news_id": 1, "news": NEWS})

    assert len(seen) == 1, f"팬인이 {len(seen)}번 돌았다 — 정확히 한 번이어야 한다"
    assert seen[0] == {"edges": ["e1"], "hits": ["t1"]}


async def test_tracks_run_concurrently(monkeypatch):
    """두 트랙이 같은 슈퍼스텝에서 동시에 돈다 — 직렬이면 배리어에서 타임아웃."""

    barrier = asyncio.Barrier(2)

    async def _rendezvous(state):
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return {}

    async def _supply(state):
        await _rendezvous(state)
        return {"supply_result": SupplySubgraphResult(edges=["e1"])}

    async def _theme(state):
        await _rendezvous(state)
        return {"theme_result": ThemeSubgraphResult(hits=["t1"])}

    seen: list[dict] = []
    graph = _fake_graph(monkeypatch, _supply, _theme, seen)
    await graph.ainvoke({"rep_news_id": 1, "news": NEWS})

    assert seen and seen[0] == {"edges": ["e1"], "hits": ["t1"]}


async def test_failed_track_does_not_discard_the_other(monkeypatch):
    """supply 가 장애여도 theme 결과가 팬인까지 간다 — 이 태스크의 존재 이유다."""

    async def _supply(state):
        return {"supply_result": SupplySubgraphResult(error="neo4j down")}

    async def _theme(state):
        return {"theme_result": ThemeSubgraphResult(hits=["t1"])}

    seen: list[dict] = []
    graph = _fake_graph(monkeypatch, _supply, _theme, seen)
    await graph.ainvoke({"rep_news_id": 1, "news": NEWS})

    assert len(seen) == 1
    assert seen[0]["hits"] == ["t1"]


# --- theme 래퍼 -----------------------------------------------------------

async def test_theme_track_skips_subgraph_when_no_probes(monkeypatch):
    """probe 가 0개면 임베딩·검색·LLM 을 통째로 건너뛴다(스펙 §4.5)."""

    class _Boom:
        async def ainvoke(self, _state):
            raise AssertionError("probe 가 없는데 서브그래프를 불렀다")

    monkeypatch.setattr(workflow, "_theme_subgraph", _Boom())

    result = await theme_track({"news": NEWS, "plan": NO_PROBES,
                                "root_companies": [], "relation_lines": []})

    assert result["theme_result"].hits == []
    assert result["theme_result"].status == "no_pool"
    assert result["theme_result"].reason


async def test_theme_track_invokes_subgraph_when_probes_exist(monkeypatch):
    class _Stub:
        async def ainvoke(self, state):
            return {"hits": ["t1"], "outcome": SubgraphResult(status="no_candidates")}

    monkeypatch.setattr(workflow, "_theme_subgraph", _Stub())

    result = await theme_track({"news": NEWS, "plan": POSITIVE,
                                "root_companies": [], "relation_lines": []})

    assert result["theme_result"].hits == ["t1"]
    assert result["theme_result"].status == "no_candidates"


# --- 정지 규칙 ------------------------------------------------------------

def test_stop_or_passes_through_only_when_not_stopped():
    route = stop_or("candidate_selector")
    assert route({"edges": [object()]}) == "candidate_selector"
    assert route({"error": "x"}) == END
    assert route({"status": "no_candidates"}) == END


def test_track_outcome_error_no_longer_stops_the_graph():
    """Task 4 의 임시 비계 제거 — 트랙 신호 판정은 selector 가 독점한다.

    _stopped 가 supply_result.error 를 다시 보면(옛 비계) 실패한다.
    """
    stopped_state = {"supply_result": SupplySubgraphResult(error="neo4j down")}
    assert stop_or("finance_collector")(stopped_state) == "finance_collector"
    assert route_after_plan({"plan": POSITIVE, **stopped_state}) != END


# --- 실패 강등 ------------------------------------------------------------

def test_every_node_registers_an_error_handler():
    # 예외는 그래프 밖으로 나가지 않는다 — 노드 하나라도 빠지면 500 이 샌다.
    # 트랙 래퍼는 예외 없이 outcome 값만 반환하므로 예외이다
    # (내부 노드의 error_handler 는 subgraphs/*/graph.py 소관).
    nodes = beneficiary_graph.nodes
    for name in ("planner", "candidate_selector", "finance_collector", "evaluator"):
        assert nodes[name].error_handler_node, f"{name} 에 error_handler 가 없다"


def test_track_wrappers_carry_no_retry_or_timeout():
    """서브그래프가 실패를 값으로 흡수한다 — 래퍼에 retry 를 걸면 LLM 중복 과금."""
    nodes = beneficiary_graph.nodes
    for name in ("supply_track", "theme_track"):
        assert nodes[name].retry_policy is None
        assert nodes[name].timeout is None
        assert nodes[name].error_handler_node is None


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

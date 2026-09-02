"""beneficiary compiled graph 조립 — 호재 두 트랙 병렬(팬아웃/팬인).

                    ┌─→ supply_track ─┐
START → planner ────┤                 ├─→ candidate_selector ─→ finance_collector ─→ evaluator → END
                    └─→ theme_track ──┘

조기 종료 출구는 planner(장애/루트 없음/악재), candidate_selector(장애/후보
없음), finance_collector(장애) 세 곳뿐이다 — 트랙에는 없다. evaluator 는
조기 종료가 아니라 정상 종점이다.

planner 는 유일한 분기다 — 정지 신호가 없으면 노드 리스트를 반환해 두 트랙을
같은 슈퍼스텝에 동시에 띄운다. 트랙은 END 로 가지 않는다: 빈손이든 장애든
자기 TrackOutcome 을 들고 팬인까지 가고, 종료 판정은 candidate_selector
한 곳이 한다(스펙 §3). 한쪽 트랙의 빈손이 다른 쪽 결과를 버리지 않게 하려는
것이고, 그래서 트랙 뒤 엣지는 조건부가 아니라 무조건 엣지다.

두 트랙은 같은 슈퍼스텝에 쓰지만 리듀서가 필요 없다 — 부모 키가 서로 겹치지
않기 때문이다. supply 는 edges·supply_outcome 을, theme 은 theme_hits·
theme_outcome 을 쓰고, 트랙 내부의 strong_ids/weak_ids 는 각 서브그래프
state 에만 있다.

정지 규칙은 하나다 — 상태에 error(장애) 나 status(정상 조기 종료) 가 들어오면
그 다음 라우터가 END 로 보낸다. planner 는 극성 게이트에서 악재를
not_positive 로 status 에 넣으므로, 나머지 엣지는 전부 stop_or 로 충분하다.
조건부 엣지는 순수 라우팅만 한다(상태 변경 금지).

status 는 노드가 직접 넣는다(더 갈 곳이 없다는 정상 판단). error 는 노드가
넣지 않는다 — 노드는 그냥 예외를 올리고, 여기 등록된 error_handler 가 그것을
error 로 강등한다. 스펙 §9(예외는 그래프 밖으로 나가지 않는다)의 구현부가
노드들의 try/except 가 아니라 이 파일 한 곳이라는 뜻이다. 덕분에 노드는
성공 경로만 쓰고, 재시도(retry_policy)·타임아웃(timeout)도 같은 자리에서
선언된다.

트랙 래퍼는 자체 예외를 내지 않는다 — 내부 실패는 서브그래프가 outcome
(TrackOutcome) 값으로 흡수한다(tracks/*/graph.py). retry_policy·timeout·
error_handler 도 그쪽 안쪽 노드에 걸려 있어 래퍼에는 아무것도 달지 않는다.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
from psycopg import OperationalError

from beneficiary.models import TrackOutcome
from beneficiary.agent.nodes import (
    build_plan,
    collect_financials,
    evaluate,
    select_candidates,
)
from beneficiary.agent.state import GraphState
from beneficiary.agent.tracks.supply import build_supply_subgraph
from beneficiary.agent.tracks.theme import build_theme_subgraph

logger = logging.getLogger(__name__)

# 인프라 일시 장애만 재시도한다 — psycopg.OperationalError 는 풀 고갈
# (PoolTimeout)까지 덮는다. LLM·검증 오류는 여기 없다: 그쪽 재시도는 체인의
# with_retry 소관이고, 노드를 통째로 다시 도는 건 LLM 호출을 중복 과금한다.
DB_RETRY = RetryPolicy(
    max_attempts=3,
    retry_on=(ServiceUnavailable, SessionExpired, TransientError, OperationalError),
)

# 시도당 상한 — 정상 지연이 아니라 멈춘 호출을 끊기 위한 값이다.
# LLM 쪽은 botocore read_timeout(120s) 위에 얹는 안전망이다.
DB_TIMEOUT = timedelta(seconds=60)
LLM_TIMEOUT = timedelta(seconds=180)


def demote_to_error(fallback: dict | Callable[[GraphState], dict]):
    """노드 예외 → error 강등 핸들러. retry_policy 가 소진된 뒤에만 불린다.

    반환한 update 가 상태에 병합되면 그 노드의 조건부 엣지가 error 를 보고
    END 로 보낸다. 대체값을 지어내는 폴백은 없다 — fallback 은 그 노드가
    쓰기로 한 키를 빈 값으로 확정할 뿐이고, 서비스는 error 를 503 으로 맵핑한다.
    """

    def handler(state: GraphState, error: NodeError) -> Command:
        logger.error("노드 실패: %s", error.node, exc_info=error.error)
        update = fallback(state) if callable(fallback) else dict(fallback)
        return Command(update={**update, "error": str(error.error)})

    return handler


def _stopped(state: GraphState) -> bool:
    """장애든 정상 조기 종료든 — 멈추기로 했으면 더 가지 않는다."""
    return bool(state.get("error") or state.get("status"))


def stop_or(next_node: str) -> Callable[[GraphState], str]:
    """정지 신호가 없으면 next_node 로 — 극성 분기를 뺀 모든 엣지가 이 형태다."""

    def route(state: GraphState) -> str:
        return END if _stopped(state) else next_node

    return route


def route_after_plan(state: GraphState) -> str | list[str]:
    """유일한 분기 — 정지 신호가 없으면 두 트랙으로 동시에 나간다.

    트랙은 END 로 가지 않는다. 빈손이든 장애든 TrackOutcome 을 들고 팬인까지
    가고, 종료 판정은 candidate_selector 한 곳이 한다(스펙 §3).
    """

    if _stopped(state):
        return END
    return ["supply_track", "theme_track"]


_supply_subgraph = build_supply_subgraph()
_theme_subgraph = build_theme_subgraph()


async def supply_track(state: GraphState) -> dict:
    """supply 서브그래프 래퍼 — 부모/자식 state 스키마를 잇는다."""
    result = await _supply_subgraph.ainvoke({
        "news": state["news"],
        "plan": state["plan"],
        "root_companies": state["root_companies"],
        "relation_lines": state["relation_lines"],
    })

    return {
        "edges": result.get("edges", []),
        "supply_outcome": result.get("outcome") or TrackOutcome()
    }


async def theme_track(state: GraphState) -> dict:
    """theme 서브그래프 래퍼.

    probe 가 0개면 서브그래프를 아예 호출하지 않는다 — 불필요한 임베딩·검색·
    LLM 호출을 건너뛴다(스펙 §4.5). planner 는 probe 0개를 조기 종료로 보지
    않는다: supply 트랙만으로 진행할 수 있기 때문이다.
    """

    plan = state["plan"]

    # Planner가 시나리오를 생성하지 않았으면 바로 반환
    if not plan.scenario_probes:
        return {
            "theme_hits": [],
            "theme_outcome": TrackOutcome(
                status="no_pool",
                reason="이 사건에서 추적할 수혜 시나리오를 세우지 못했습니다."
            )
        }
    
    result = await _theme_subgraph.ainvoke({
        "news": state["news"],
        "plan": plan,
        "root_companies": state["root_companies"],
        "relation_lines": state["relation_lines"],
    })

    return {
        "theme_hits": result.get("hits", []),
        "theme_outcome": result.get("outcome") or TrackOutcome()
    }


def build_beneficiary_graph():
    builder = StateGraph(GraphState)
    builder.add_node(
        "planner", build_plan,
        retry_policy=DB_RETRY, timeout=LLM_TIMEOUT,  # DB 조회 후 LLM#1
        error_handler=demote_to_error(
            {"root_companies": [], "relation_lines": [], "plan": None}
        ),
    )
    # 래퍼는 예외를 내지 않는다 — retry_policy·timeout·error_handler 없음
    builder.add_node("supply_track", supply_track)
    builder.add_node("theme_track", theme_track)
    builder.add_node(
        "candidate_selector", select_candidates,
        error_handler=demote_to_error({"candidates": []}),  # 순수 로직 — 재시도·타임아웃 없음
    )
    builder.add_node(
        "finance_collector", collect_financials,
        retry_policy=DB_RETRY, timeout=DB_TIMEOUT,
        error_handler=demote_to_error({"candidates": []}),
    )
    builder.add_node(
        "evaluator", evaluate,
        timeout=LLM_TIMEOUT,
        error_handler=demote_to_error(
            lambda state: {"items": [], "pool_size": len(state.get("candidates", []))}
        ),
    )

    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner", route_after_plan, ["supply_track", "theme_track", END]
    )
    builder.add_edge("supply_track", "candidate_selector")
    builder.add_edge("theme_track", "candidate_selector")
    builder.add_conditional_edges(
        "candidate_selector", stop_or("finance_collector"), ["finance_collector", END]
    )
    builder.add_conditional_edges(
        "finance_collector", stop_or("evaluator"), ["evaluator", END]
    )
    builder.add_edge("evaluator", END)
    return builder.compile()


beneficiary_graph = build_beneficiary_graph()

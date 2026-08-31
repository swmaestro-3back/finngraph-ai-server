"""beneficiary compiled graph 조립 — 호재 단일 선형 트랙.

START → planner ─(장애/데이터 없음/악재)─→ END
   → supply_track (expand_supply → filter_supply 서브그래프)
   → candidate_selector → finance_collector → evaluator → END

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

supply_track 은 자체 예외를 내지 않는 래퍼다 — 내부 실패는 서브그래프가
supply_outcome(TrackOutcome) 값으로 흡수한다(tracks/supply/graph.py). candidate_selector
가 아직 supply_outcome 을 읽지 않으므로, _stopped 가 그 error 를 봐서 대신
멈춘다 — candidate_selector 가 이걸 읽게 되면(추후 태스크) 이 특례는 걷어낸다.
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
    outcome = state.get("supply_outcome")
    if outcome is not None and outcome.error:
        return True
    return bool(state.get("error") or state.get("status"))


def stop_or(next_node: str) -> Callable[[GraphState], str]:
    """정지 신호가 없으면 next_node 로 — 극성 분기를 뺀 모든 엣지가 이 형태다."""

    def route(state: GraphState) -> str:
        return END if _stopped(state) else next_node

    return route


_supply_subgraph = build_supply_subgraph()


async def supply_track(state: GraphState) -> dict:
    """supply 서브그래프 래퍼 — 부모/자식 state 스키마를 잇는다."""
    result = await _supply_subgraph.ainvoke({
        "news": state["news"], "plan": state["plan"],
        "root_companies": state["root_companies"],
        "relation_lines": state["relation_lines"],
    })
    return {"edges": result.get("edges", []),
            "supply_outcome": result.get("outcome") or TrackOutcome()}


def build_beneficiary_graph():
    builder = StateGraph(GraphState)
    builder.add_node(
        "planner", build_plan,
        retry_policy=DB_RETRY, timeout=LLM_TIMEOUT,  # DB 조회 후 LLM#1
        error_handler=demote_to_error(
            {"root_companies": [], "relation_lines": [], "plan": None}
        ),
    )
    builder.add_node("supply_track", supply_track)  # 래퍼는 예외를 내지 않는다 — error_handler 없음
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
        "planner", stop_or("supply_track"), ["supply_track", END]
    )
    builder.add_conditional_edges(
        "supply_track", stop_or("candidate_selector"), ["candidate_selector", END]
    )
    builder.add_conditional_edges(
        "candidate_selector", stop_or("finance_collector"), ["finance_collector", END]
    )
    builder.add_conditional_edges(
        "finance_collector", stop_or("evaluator"), ["evaluator", END]
    )
    builder.add_edge("evaluator", END)
    return builder.compile()


beneficiary_graph = build_beneficiary_graph()

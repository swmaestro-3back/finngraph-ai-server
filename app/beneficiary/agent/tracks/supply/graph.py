"""supply 트랙 서브그래프 — expand_supply → filter_supply.

트랙은 END 로 조기 종료하되 그것은 서브그래프 종료일 뿐이다(스펙 §3). 부모는
outcome 을 값으로 받아 팬인에서 집계한다 — 여기서 전체 종료로 승격하지 않는다.

retry_policy·timeout·error_handler 는 여기 안쪽 노드에 건다. 트랙 전체에 retry 를
걸면 안쪽 LLM#2 를 중복 과금한다.
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
from beneficiary.agent.tracks.supply import nodes
from beneficiary.agent.tracks.supply.state import SupplyTrackState

logger = logging.getLogger(__name__)

DB_RETRY = RetryPolicy(
    max_attempts=3,
    retry_on=(ServiceUnavailable, SessionExpired, TransientError, OperationalError),
)
DB_TIMEOUT = timedelta(seconds=60)
LLM_TIMEOUT = timedelta(seconds=180)


def demote_to_outcome(fallback: dict) -> Callable:
    """노드 예외 → outcome.error. 서브그래프 밖으로 예외를 내보내지 않는다."""

    def handler(state: SupplyTrackState, error: NodeError) -> Command:
        logger.error("supply 트랙 노드 실패: %s", error.node, exc_info=error.error)
        return Command(update={**fallback, "outcome": TrackOutcome(error=str(error.error))})

    return handler


def _after_expand(state: SupplyTrackState) -> str:
    return END if state.get("outcome") or not state.get("edges") else "filter_supply"


async def _expand(state: SupplyTrackState) -> dict:
    result = await nodes.expand_supply(state)
    if not result.get("edges"):
        return result | {"outcome": TrackOutcome(
            status="no_pool",
            reason="루트 기업에 납품하는 상장 공급사를 그래프에서 찾지 못했습니다.",
        )}
    return result


async def _filter(state: SupplyTrackState) -> dict:
    result = await nodes.filter_supply(state)
    status = result.pop("status", None)
    reason = result.pop("reason", None)
    if status:
        return result | {"outcome": TrackOutcome(status=status, reason=reason)}
    return result | {"outcome": state.get("outcome") or TrackOutcome()}


def build_supply_subgraph():
    builder = StateGraph(SupplyTrackState)
    builder.add_node("expand_supply", _expand,
                     retry_policy=DB_RETRY, timeout=DB_TIMEOUT,
                     error_handler=demote_to_outcome({"edges": []}))
    # 선별이 실패하면 남은 간선은 전부 relevance=None 이라 쓸 수 없다 — 원시
    # 리스트까지 비워야 팬인이 "원시 행은 있다"고 오해하지 않는다.
    builder.add_node("filter_supply", _filter,
                     timeout=LLM_TIMEOUT,
                     error_handler=demote_to_outcome(
                         {"edges": [], "strong_ids": [], "weak_ids": []}))

    builder.add_edge(START, "expand_supply")
    builder.add_conditional_edges("expand_supply", _after_expand, ["filter_supply", END])
    builder.add_edge("filter_supply", END)

    return builder.compile()

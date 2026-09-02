"""theme 트랙 서브그래프 — expand_theme → filter_theme.

supply 트랙과 같은 규약이다: 내부 END 는 서브그래프 종료일 뿐이고, 부모는
outcome 을 값으로 받는다. 예외는 서브그래프 밖으로 나가지 않는다(스펙 §5.1).

retry_policy·timeout·error_handler 는 여기 안쪽 노드에 건다. 트랙 전체에 retry 를
걸면 안쪽 LLM#2 를 중복 과금한다. DB_RETRY 는 psycopg.OperationalError 를 잡지
않는다 — 이 트랙은 Neo4j 만 읽고 Postgres 는 건드리지 않는다.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError

from beneficiary.models import SubgraphResult
from beneficiary.agent.subgraphs.theme import nodes
from beneficiary.agent.subgraphs.theme.state import ThemeTrackState

logger = logging.getLogger(__name__)

DB_RETRY = RetryPolicy(
    max_attempts=3,
    retry_on=(ServiceUnavailable, SessionExpired, TransientError),
)
DB_TIMEOUT = timedelta(seconds=60)
LLM_TIMEOUT = timedelta(seconds=180)


def demote_to_outcome(fallback: dict) -> Callable:
    """노드 예외 → outcome.error. 서브그래프 밖으로 예외를 내보내지 않는다."""

    def handler(state: ThemeTrackState, error: NodeError) -> Command:
        logger.error("theme 트랙 노드 실패: %s", error.node, exc_info=error.error)
        return Command(update={**fallback, "outcome": SubgraphResult(error=str(error.error))})

    return handler


def _after_expand(state: ThemeTrackState) -> str:
    return END if state.get("outcome") or not state.get("hits") else "filter_theme"


async def _expand(state: ThemeTrackState) -> dict:
    result = await nodes.expand_theme(state)
    if not result.get("hits"):
        return result | {"outcome": SubgraphResult(
            status="no_pool",
            reason="시나리오와 맞는 테마 편입 사유를 가진 상장 기업을 찾지 못했습니다.",
        )}
    return result


async def _filter(state: ThemeTrackState) -> dict:
    result = await nodes.filter_theme(state)
    status = result.pop("status", None)
    reason = result.pop("reason", None)
    if status:
        return result | {"outcome": SubgraphResult(status=status, reason=reason)}
    return result | {"outcome": state.get("outcome") or SubgraphResult()}


def build_theme_subgraph():
    builder = StateGraph(ThemeTrackState)
    builder.add_node("expand_theme", _expand,
                     retry_policy=DB_RETRY, timeout=DB_TIMEOUT,
                     error_handler=demote_to_outcome({"hits": []}))
    # 선별이 실패하면 남은 히트는 전부 relevance=None 이라 쓸 수 없다 — 원시
    # 리스트까지 비워야 팬인이 "원시 행은 있다"고 오해하지 않는다.
    builder.add_node("filter_theme", _filter,
                     timeout=LLM_TIMEOUT,
                     error_handler=demote_to_outcome(
                         {"hits": [], "strong_ids": [], "weak_ids": []}))
    builder.add_edge(START, "expand_theme")
    builder.add_conditional_edges("expand_theme", _after_expand, ["filter_theme", END])
    builder.add_edge("filter_theme", END)
    return builder.compile()

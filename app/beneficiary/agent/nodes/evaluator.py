"""evaluator 노드 (LLM#3, Sonnet) — 5단계 재무 체크리스트 심사·랭킹.

패킹·LLM·후처리 실패는 예외로 올려보내고 그래프가 error 로 강등한다
(workflow 의 error_handler → END → 서비스가 503 으로 매핑).
"""

from __future__ import annotations

import logging
import time

from beneficiary.agent.state import GraphState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_evaluator_context
from beneficiary.agent.utils.postprocess import validate_and_rank

logger = logging.getLogger(__name__)


async def evaluate(state: GraphState) -> dict:
    started = time.monotonic()
    candidates = state["candidates"]

    packed = pack_evaluator_context(
        state["news"], state["root_companies"], state["plan"], candidates
    )
    evaluator_output = await llm.evaluate_beneficiary(packed.prompt)
    items = validate_and_rank(evaluator_output, packed.by_cid, packed.eids_by_cid)

    logger.info(
        "evaluator: %.1fs (후보 %d → 추천 %d)",
        time.monotonic() - started, len(candidates), len(items),
    )
    return {
        "items": items,
        "pool_size": len(candidates),
        "event_interpretation": evaluator_output.event_interpretation,
        "status": "ok" if items else "no_beneficiaries",
        "reason": None if items else "심사 결과 수혜로 볼 만한 후보가 없습니다.",
    }

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
from beneficiary.models import TrackOutcome

logger = logging.getLogger(__name__)


def build_track_note(supply: TrackOutcome, theme: TrackOutcome) -> str | None:
    """탐색 축 현황을 사용자 문장으로 — 프롬프트가 아니라 코드가 보증한다(스펙 §7.6).

    "후보가 없었다"와 "장애로 못 돌았다"는 사용자에게 의미가 완전히 다르다.
    """

    if theme.error:
        return "시나리오 테마 축 탐색이 실패해 공급망 축만으로 도출된 결과입니다."
    if supply.error:
        return "공급망 축 탐색이 실패해 시나리오 테마 축만으로 도출된 결과입니다."
    if theme.status:
        return "시나리오 테마 축에서는 후보를 찾지 못해 공급망 축만으로 도출된 결과입니다."
    if supply.status:
        return "공급망 축에서는 후보를 찾지 못해 시나리오 테마 축만으로 도출된 결과입니다."
    return None


async def evaluate(state: GraphState) -> dict:
    started = time.monotonic()
    candidates = state["candidates"]

    packed = pack_evaluator_context(
        state["news"], state["root_companies"], state["plan"], candidates
    )
    evaluator_output = await llm.evaluate_beneficiary(packed.prompt)
    track_note = build_track_note(
        state.get("supply_outcome") or TrackOutcome(),
        state.get("theme_outcome") or TrackOutcome(),
    )
    items = validate_and_rank(evaluator_output, packed.by_cid, packed.eids_by_cid,
                              track_note=track_note)

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

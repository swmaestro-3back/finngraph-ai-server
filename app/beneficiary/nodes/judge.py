"""judge 노드 (LLM#3, Sonnet) — 5단계 재무 체크리스트 심사·랭킹.

실패는 error 로 강등한다(그래프를 죽이지 않고 서비스가 503 으로 매핑).
"""

from __future__ import annotations

import logging
import time

from beneficiary.state import GraphState
from beneficiary.utils import llm
from beneficiary.utils.packer import pack_judge_context
from beneficiary.utils.postprocess import validate_and_rank

logger = logging.getLogger(__name__)


def _fallback_note(state: GraphState) -> str | None:
    notes = []
    if state.get("plan_fallback"):
        notes.append("계획 폴백(LLM 실패 — 원장 기반 자동 계획)")
    if state.get("probe_fallback"):
        notes.append("probe 보강(결정적 재구성)")
    if state.get("filter_fallback"):
        notes.append("선별 폴백(카운트/겹침 기반)")
    return " / ".join(notes) if notes else None


async def judge(state: GraphState) -> dict:
    started = time.monotonic()
    candidates = state["candidates"]
    # 패킹·후처리 예외도 error 로 강등한다 — 예외는 그래프 밖으로 나가지
    # 않는다(스펙 §9).
    try:
        packed = pack_judge_context(
            state["news"], state["root_companies"], state["plan"], candidates,
            fallback_note=_fallback_note(state),
        )
        judge_output = await llm.judge_beneficiary(packed.prompt)
        items = validate_and_rank(judge_output, packed.by_cid, packed.eids_by_cid)
    except Exception as error:
        logger.exception("수혜주 심사 실패")
        return {"items": [], "pool_size": len(candidates), "error": str(error)}

    logger.info(
        "judge: %.1fs (후보 %d → 추천 %d)",
        time.monotonic() - started, len(candidates), len(items),
    )
    return {
        "items": items,
        "pool_size": len(candidates),
        "event_interpretation": judge_output.event_interpretation,
    }

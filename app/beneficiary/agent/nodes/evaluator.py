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
from beneficiary.models import SubgraphResult

logger = logging.getLogger(__name__)


def build_track_note(supply: SubgraphResult, theme: SubgraphResult) -> str | None:
    """탐색 축 현황을 사용자 문장으로 — 프롬프트가 아니라 코드가 보증한다(스펙 §7.6).

    "후보가 없었다"와 "장애로 못 돌았다"는 사용자에게 의미가 완전히 다르다.

    이 문장은 개별 종목의 한계가 아니라 이번 분석 전체의 성격이다 — 그래서
    항목마다 붙지 않고 응답의 analysis_note 로 한 번만 나간다.
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
    items = validate_and_rank(evaluator_output, packed.by_cid, packed.eids_by_cid)
    analysis_note = build_track_note(
        state.get("supply_result") or SubgraphResult(),
        state.get("theme_result") or SubgraphResult(),
    )

    # 수혜 아님(no_impact)까지 같이 찍는다 — 후보 4 → 추천 1 일 때 나머지 3 이
    # LLM 이 탈락시킨 것인지 후처리(자기 근거 부재·시장 쿼터)가 떨어뜨린 것인지
    # 로그만으로 갈린다. no_impact_ids 는 코드가 쓰지 않는 값이라 여기가 유일한
    # 관측 지점이다.
    logger.info(
        "evaluator: %.1fs (후보 %d → 추천 %d, 수혜 아님 %d)",
        time.monotonic() - started, len(candidates), len(items),
        len(evaluator_output.no_impact_ids),
    )
    return {
        "items": items,
        "analysis_note": analysis_note,
        "event_interpretation": evaluator_output.event_interpretation,
        "status": "ok" if items else "no_beneficiaries",
        "reason": None if items else "심사 결과 수혜로 볼 만한 후보가 없습니다.",
    }

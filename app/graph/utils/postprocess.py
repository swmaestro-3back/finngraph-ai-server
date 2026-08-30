"""LLM 출력 후처리 — 프롬프트를 신뢰하지 않는 안전망.

apply_filter_output: 선별(LLM#2) 재강제 — 두 filter 노드 공용.
validate_and_rank(Task 13): 심사(LLM#3) 재강제 — v1 복사 + 후보별 eid 스코프
+ 시장 쿼터 코드 강제.
"""

from __future__ import annotations

import re

from graph.models import Candidate, FilterOutput, JudgeOutput, RankedItem


def apply_filter_output(
    output: FilterOutput,
    by_id: dict[str, object],
    cap_weak_ids: set[str],
) -> tuple[list[str], list[str]]:
    """선별 출력 재강제 — 대상 객체의 relevance 를 세팅하고 (strong, weak) id 반환.

    규칙(스펙 §4.3/§4.5): 미존재 id 폐기, strong∩weak 중복은 strong 우선,
    아이템 없는 후보(cap_weak_ids)는 최대 weak(strong 금지 — 코드로 강등),
    응답에서 빠진 id 는 irrelevant. 순서는 LLM 출력 순서를 보존하고 강등분은
    weak 뒤에 붙인다(결정적).
    """

    strong_ids: list[str] = []
    demoted: list[str] = []
    for candidate_id in dict.fromkeys(output.strong):
        if candidate_id not in by_id:
            continue
        if candidate_id in cap_weak_ids:
            demoted.append(candidate_id)
        else:
            strong_ids.append(candidate_id)

    weak_ids = [
        candidate_id for candidate_id in dict.fromkeys(output.weak)
        if candidate_id in by_id and candidate_id not in strong_ids and candidate_id not in demoted
    ]
    weak_ids.extend(demoted)

    for candidate_id, candidate in by_id.items():
        if candidate_id in strong_ids:
            candidate.relevance = "strong"
        elif candidate_id in weak_ids:
            candidate.relevance = "weak"
        else:
            candidate.relevance = "irrelevant"
    return strong_ids, weak_ids


CITATION_RE = re.compile(r"\[e\d+\]")

RECOMMEND_PER_MARKET = 2  # 최종 추천 시장당 상한 — 프롬프트만으로 2+2 를 보증하지 않는다


def validate_and_rank(
    judge: JudgeOutput,
    by_cid: dict[str, Candidate],
    eids_by_cid: dict[str, set[str]],
) -> list[RankedItem]:
    """심사 출력 재강제 — v1 복사 + 강화 2건(스펙 §4.8).

    ① eid 검증은 후보별 스코프: insight 의 evidence_ids 는 그 후보 자신의 eid
    집합에 속해야 한다(전역 집합 검증은 남의 근거로 접지되는 구멍).
    ② 시장 쿼터 코드 강제: insight 순서를 유지하며 시장별 최대 2개만 남긴다.
    기존 규칙(비실존 cid/eid 폐기, 인용 없는 rationale low 강등, 중복 cid 첫
    판정만, benefit 아닌 impact 폐기)은 유지 — impact 는 pydantic Literal 로도
    막혀 있지만 방어적으로 한 번 더 거른다.
    """

    items: list[RankedItem] = []
    seen_cids: set[str] = set()

    for insight in judge.insights:
        candidate = by_cid.get(insight.candidate_id)
        if candidate is None or insight.impact != "benefit":
            continue
        if insight.candidate_id in seen_cids:
            continue
        seen_cids.add(insight.candidate_id)

        scope = eids_by_cid.get(insight.candidate_id, set())
        evidence_ids = [eid for eid in insight.evidence_ids if eid in scope]
        if not evidence_ids:
            # 자기 근거가 하나도 없는 판단은 접지되지 않았으므로 버린다.
            continue

        confidence = insight.confidence
        if not CITATION_RE.search(insight.rationale):
            confidence = "low"

        items.append(RankedItem(
            candidate=candidate,
            impact=insight.impact,
            confidence=confidence,
            rationale=insight.rationale,
            caveats=insight.caveats,
            evidence_ids=evidence_ids,
        ))

    per_market: dict[str, int] = {}
    trimmed: list[RankedItem] = []
    for item in items:
        market = item.candidate.market or "시장 미상"
        if per_market.get(market, 0) >= RECOMMEND_PER_MARKET:
            continue
        per_market[market] = per_market.get(market, 0) + 1
        trimmed.append(item)

    for position, item in enumerate(trimmed, start=1):
        item.rank = position
    return trimmed

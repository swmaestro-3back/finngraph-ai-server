"""심사 출력 후처리 — 프롬프트를 신뢰하지 않는 안전망.

전달하지 않은 후보/근거 id 는 폐기하고, 근거 인용 규칙을 코드에서 재강제한다.
순위는 심사가 낸 순서(재무 체크리스트 기준 랭킹)를 그대로 따른다.
"""

from __future__ import annotations

import re

from graph.models import Candidate, JudgeOutput, RankedItem

CITATION_RE = re.compile(r"\[e\d+\]")


def validate_and_rank(
    judge: JudgeOutput,
    by_cid: dict[str, Candidate],
    known_eids: set[str],
) -> list[RankedItem]:
    items: list[RankedItem] = []
    seen_cids: set[str] = set()

    for insight in judge.insights:
        candidate = by_cid.get(insight.candidate_id)
        if candidate is None or insight.impact == "neutral":
            continue
        # 심사가 같은 후보를 중복으로 내면 첫 판정만 취한다.
        if insight.candidate_id in seen_cids:
            continue
        seen_cids.add(insight.candidate_id)

        evidence_ids = [eid for eid in insight.evidence_ids if eid in known_eids]
        if not evidence_ids:
            # 실존 근거가 하나도 없는 판단은 접지되지 않았으므로 버린다.
            continue

        confidence = insight.confidence
        if not CITATION_RE.search(insight.rationale):
            confidence = "low"

        items.append(
            RankedItem(
                candidate=candidate,
                impact=insight.impact,
                confidence=confidence,
                rationale=insight.rationale,
                caveats=insight.caveats,
                evidence_ids=evidence_ids,
            )
        )

    for position, item in enumerate(items, start=1):
        item.rank = position
    return items

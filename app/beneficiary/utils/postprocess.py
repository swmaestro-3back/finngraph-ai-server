"""LLM 출력 후처리 — 프롬프트를 신뢰하지 않는 안전망.

apply_filter_output: 선별(LLM#2) 재강제 — 두 filter 노드 공용.
validate_and_rank(Task 13): 심사(LLM#3) 재강제 — v1 복사 + 후보별 eid 스코프
+ 시장 쿼터 코드 강제.
"""

from __future__ import annotations

from beneficiary.models import FilterOutput


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

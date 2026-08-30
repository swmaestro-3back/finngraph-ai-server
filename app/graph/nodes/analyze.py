"""analyze_news 노드 (LLM#1) — 뉴스 → 계획(극성·핵심 아이템·rival probe).

실패 구분(스펙 §4.1/§9): DB 실패는 error 강등(→ END → 503), LLM 실패는
정형 폴백 계획으로 계속 진행(plan_fallback). 루트 기업은 상장 국내 기업만 —
해외·비상장 subject 는 걸러내며, 상장 루트 기업 0명이면 정상 조기 종료.
"""

from __future__ import annotations

import logging

from graph import repository
from graph.models import RootCompany, NewsPlan, RelationLine, RivalProbe
from graph.state import GraphState
from graph.utils import llm
from graph.utils.packer import pack_plan_context
from core import postgres_database

logger = logging.getLogger(__name__)

CORE_ITEMS_CAP = 5
FALLBACK_PROBE_THEMES = 3
FALLBACK_SUMMARY = "(자동 폴백) 뉴스 관계 원장 기반 탐색"


def _is_affirmed(line: RelationLine) -> bool:
    return line.polarity is None or line.polarity == "affirmed"


def build_fallback_plan(relation_lines: list[RelationLine]) -> NewsPlan:
    """LLM 실패 시의 정형 계획 — affirmed 행만 신호로 쓴다.

    극성은 subject_impact 의 positive/negative 행만 투표(neutral·NULL 제외),
    0행·동률이면 positive. core_items 는 affirmed 행의 item 중복 제거 상한 5.
    """

    affirmed = [line for line in relation_lines if _is_affirmed(line)]
    votes = [line.subject_impact for line in affirmed
             if line.subject_impact in ("positive", "negative")]
    polarity = "negative" if votes.count("negative") > votes.count("positive") else "positive"
    core_items = list(dict.fromkeys(
        line.item for line in affirmed if line.item
    ))[:CORE_ITEMS_CAP]
    return NewsPlan(event_summary=FALLBACK_SUMMARY, polarity=polarity,
                    core_items=core_items, rival_probes=[])


def sanitize_plan(plan: NewsPlan, themes_by_root: dict[str, list[dict]]) -> NewsPlan:
    """LLM 출력 재강제 — 목록 밖 subject/theme 폐기, dedup, positive 는 probe 제거."""

    core_items = list(dict.fromkeys(item for item in plan.core_items if item))[:CORE_ITEMS_CAP]

    probes: list[RivalProbe] = []
    if plan.polarity == "negative":
        seen_subjects: set[str] = set()
        for probe in plan.rival_probes:
            themes = themes_by_root.get(probe.subject_name)
            if themes is None or probe.subject_name in seen_subjects:
                continue
            valid_names = {theme["name"] for theme in themes}
            picked = list(dict.fromkeys(t for t in probe.themes if t in valid_names))[:3]
            if not picked:
                continue
            seen_subjects.add(probe.subject_name)
            probes.append(RivalProbe(subject_name=probe.subject_name, themes=picked))

    return plan.model_copy(update={"core_items": core_items, "rival_probes": probes})


def build_probe_fallback(themes_by_root: dict[str, list[dict]]) -> list[RivalProbe]:
    """결정적 probe 재구성 — 루트 기업별 테마 상위 3개(이미 멤버 수 asc → 이름 asc 정렬).

    LLM 이 정규명 대신 약칭을 내는 비결정성으로 데이터 있는 뉴스가 빈 응답이
    되는 것을 방지한다(스펙 §4.1).
    """

    return [
        RivalProbe(subject_name=name, themes=[t["name"] for t in themes[:FALLBACK_PROBE_THEMES]])
        for name, themes in themes_by_root.items()
        if themes
    ]


async def analyze_news(state: GraphState) -> dict:
    try:
        return await _analyze_news(state)
    except Exception as error:
        logger.exception("뉴스 분석 실패")
        return {"root_companies": [], "relation_lines": [], "plan": None, "error": str(error)}


async def _analyze_news(state: GraphState) -> dict:
    async with postgres_database.connection() as conn:
        raw_parties = await repository.fetch_root_companies(conn, state["rep_news_id"])
        # 루트 기업 = 상장 국내 subject 만 (사용자 확정) — 해외·비상장 subject 는
        # 루트 기업가 아니다. 걸러낸 당사자의 name 은 relation_lines 경유로 제외
        # 집합에는 여전히 들어간다(derive_exclusions).
        root_companies = [
            RootCompany(company_id=row["company_id"], name=row["name"],
                   ticker=row["ticker"], description=row["description"])
            for row in raw_parties
            if row["ticker"] is not None and row["company_id"] is not None
        ]
        if not root_companies:
            return {"root_companies": [], "relation_lines": [], "plan": None}
        relation_lines = await repository.fetch_relation_lines(conn, state["rep_news_id"])

    themes_by_root: dict[str, list[dict]] = {}
    for root in root_companies:
        themes = await repository.fetch_root_company_themes(root.name)
        if themes:
            themes_by_root[root.name] = themes

    plan_fallback = False
    try:
        plan = await llm.plan_news(
            pack_plan_context(state["news"], root_companies, relation_lines, themes_by_root)
        )
    except Exception:
        logger.exception("계획 LLM 실패 — 정형 폴백 계획으로 진행")
        plan = build_fallback_plan(relation_lines)
        plan_fallback = True

    plan = sanitize_plan(plan, themes_by_root)

    probe_fallback = False
    if plan.polarity == "negative" and not plan.rival_probes and themes_by_root:
        plan = plan.model_copy(update={"rival_probes": build_probe_fallback(themes_by_root)})
        probe_fallback = True

    return {
        "root_companies": root_companies,
        "relation_lines": relation_lines,
        "plan": plan,
        "plan_fallback": plan_fallback,
        "probe_fallback": probe_fallback,
    }

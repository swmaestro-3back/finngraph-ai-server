"""planner 노드 (LLM#1) — 뉴스 → 계획(극성·핵심 아이템·rival probe).

실패 구분(스펙 §4.1/§9): DB·LLM 실패는 예외로 올려보내고 그래프가
error 로 강등한다(workflow 의 error_handler → END → 503). 데이터가 없어 더
갈 곳이 없으면 status·reason 을 넣고 정상 종료한다 — 계획을 지어내는
폴백은 없다. 루트 기업은 상장 국내 기업만 — 해외·비상장
subject 는 걸러내며, 상장 루트 기업 0명이면 no_root_companies 로 끝난다.
"""

from __future__ import annotations

import asyncio

from beneficiary import repository
from beneficiary.models import RootCompany, NewsPlan, RivalProbe
from beneficiary.agent.state import GraphState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_plan_context
from core import postgres_client

CORE_ITEMS_CAP = 5

async def fetch_themes_by_root(root_companies: list[RootCompany]) -> dict[str, list[dict]]:
    """루트 기업별 테마 조회는 서로 독립이다 — 순차 await 하지 않는다."""

    themes_per_root = await asyncio.gather(
        *(repository.fetch_root_company_themes(root.name) for root in root_companies)
    )
    return {
        root.name: themes
        for root, themes in zip(root_companies, themes_per_root)
        if themes
    }


def to_root_companies(rows: list[dict]) -> list[RootCompany]:
    """당사자 행 → 루트 기업 — 상장 국내 subject 만 (사용자 확정).

    해외·비상장 subject 는 루트 기업이 아니다. 걸러낸 당사자의 name 은
    relation_lines 경유로 제외 집합에는 여전히 들어간다(derive_exclusions).
    """

    return [
        RootCompany(company_id=row["company_id"], name=row["name"],
                    ticker=row["ticker"], description=row["description"])
        for row in rows
        if row["ticker"] is not None and row["company_id"] is not None
    ]

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


async def build_plan(state: GraphState) -> dict:
    async with postgres_client.connection() as conn:
        # Root Company 조회
        root_companies = to_root_companies(
            await repository.fetch_root_companies(conn, state["rep_news_id"])
        )

        # 만약 RootCompany가 없다면 바로 반환
        if not root_companies:
            return {"root_companies": [], "relation_lines": [], "plan": None,
                    "status": "no_root_companies",
                    "reason": "이 뉴스에서 상장 국내 기업 당사자를 찾지 못했습니다."}

        # 뉴스에서 추출된 관계 조회
        relation_lines = await repository.fetch_relation_lines(conn, state["rep_news_id"])

    themes_by_root = await fetch_themes_by_root(root_companies)

    # LLM 실패를 정형 계획으로 덮지 않는다 — 예외는 그래프가 error 로 강등한다.
    plan = sanitize_plan(
        await llm.plan_news(
            pack_plan_context(state["news"], root_companies, relation_lines, themes_by_root)
        ),
        themes_by_root,
    )

    result = {"root_companies": root_companies, "relation_lines": relation_lines, "plan": plan}
    # 악재인데 유효 probe 0 — LLM 이 목록 밖 이름을 냈거나 테마 자체가 없다.
    # 어느 쪽이든 탐색할 경쟁사 축이 없으므로 여기서 끝낸다.
    if plan.polarity == "negative" and not plan.rival_probes:
        result |= {"status": "no_pool",
                   "reason": "악재의 반사이익을 볼 경쟁사를 탐색할 공유 테마가 없습니다."}
    return result

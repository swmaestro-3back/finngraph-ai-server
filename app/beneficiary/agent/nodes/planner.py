"""planner 노드 (LLM#1) — 뉴스 → 계획(극성 게이트·핵심 아이템·시나리오 probe).

실패 구분(스펙 §4.5/§9): DB·LLM 실패는 예외로 올려보내고 그래프가 error 로
강등한다. 데이터가 없어 더 갈 곳이 없으면 status·reason 을 넣고 정상 종료한다.

조기 종료는 둘뿐이다 — no_root_companies, not_positive. scenario_probes 가
0개여도 종료하지 않는다: supply 트랙만으로 진행할 수 있고, 풀이 정말 비었는지는
candidate_selector 가 팬인에서 판정한다.
"""

from __future__ import annotations

from beneficiary import repository
from beneficiary.models import RootCompany, NewsPlan, ScenarioProbe
from beneficiary.agent.state import GraphState
from beneficiary.agent.utils import llm
from beneficiary.agent.utils.packer import pack_plan_context
from core import postgres_client

CORE_ITEMS_CAP = 5
SCENARIO_PROBES_CAP = 4


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


def normalize_plan(plan: NewsPlan) -> NewsPlan:
    """LLM 출력 재강제 — 화이트리스트가 없으므로 형태 검증만 한다(스펙 §4.3).

    이전 판의 목록 대조(루트 기업명·테마명)는 사라졌다. 벡터 검색은 임의
    문자열을 받으므로 검증할 목록이 없고, 그 방어선은 theme 트랙의 유사도
    임계값과 filter_theme 로 옮겨갔다(스펙 §4.4).
    """

    core_items = list(dict.fromkeys(item for item in plan.core_items if item))[:CORE_ITEMS_CAP]

    probes: list[ScenarioProbe] = []
    if plan.polarity == "positive":
        seen: set[tuple[int, str]] = set()
        for probe in plan.scenario_probes:
            query = probe.query.strip()
            # 가설은 3~4문장이라 줄바꿈이 섞여 나올 수 있다 — 패킹은 후보 한 줄
            # 형식이므로 여기서 공백으로 접어 한 줄 계약을 지킨다.
            hypothesis = " ".join(probe.hypothesis.split())
            key = (probe.stage, query)
            if not query or not hypothesis or key in seen:
                continue
            seen.add(key)
            probes.append(probe.model_copy(update={"hypothesis": hypothesis}))
        probes = probes[:SCENARIO_PROBES_CAP]

    return plan.model_copy(update={"core_items": core_items, "scenario_probes": probes})


async def build_plan(state: GraphState) -> dict:
    async with postgres_client.connection() as conn:
        # Root Company 조회
        root_companies = to_root_companies(
            await repository.fetch_root_companies(conn, state["rep_news_id"])
        )

        # Root Company가 없다면 종료
        if not root_companies:
            return {
                "root_companies": [],
                "relation_lines": [],
                "plan": None,
                "status": "no_root_companies",
                "reason": "이 뉴스에서 상장 국내 기업 당사자를 찾지 못했습니다."
            }

        # 뉴스 내 관계 조회
        relation_lines = await repository.fetch_relation_lines(conn, state["rep_news_id"])

    # LLM 실패를 정형 계획으로 덮지 않는다 — 예외는 그래프가 error 로 강등한다.
    plan = normalize_plan(
        await llm.plan_news(pack_plan_context(state["news"], root_companies, relation_lines))
    )

    result = {"root_companies": root_companies, "relation_lines": relation_lines, "plan": plan}
    # 극성 게이트 — 상류 오분류 방어선. 악재에 수혜주를 추천하지 않는다.
    if plan.polarity != "positive":
        result |= {"status": "not_positive",
                   "reason": "호재로 보기 어려운 뉴스입니다 — 수혜 분석 대상이 아닙니다."}
    return result

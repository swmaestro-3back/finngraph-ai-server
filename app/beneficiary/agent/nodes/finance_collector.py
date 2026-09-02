"""finance_collector 노드 — 확정 후보에 근거·재무(TableRAG)를 적재한다.

TableRAG 는 고정 쿼리 테이블 패킹이다 — text2SQL 금지(스키마·체크리스트 고정).

근거 0건 후보는 제거한다: entities_relations 뷰가 polarity 를 거르지 않아
denied/terminated 행만으로 만들어진 간선이 후보를 만들 수 있는데, 그 후보는
인용 가능한 [eNN] 이 없어 심사가 접지되지 않는다(스펙 §4.7).

제거 판정은 두 축을 모두 적재한 뒤 evidence 전체로 한다(스펙 §7.4) — 실제로
걸리는 건 순수 supply 후보뿐이다: _load_theme_evidence 가 트리거 뉴스를 항상
1건 넣으므로 theme·both 후보는 이 게이트에 걸릴 수 없다.
"""

from __future__ import annotations

import logging

from beneficiary import repository
from beneficiary.models import Candidate, Evidence
from beneficiary.agent.state import GraphState
from core import postgres_client

logger = logging.getLogger(__name__)

EVIDENCE_PER_EDGE = 3  # 간선당 최신 근거 수
EVIDENCE_PER_CANDIDATE = 6
FINANCIAL_YEARS = 5  # table RAG 로 넣는 연간 재무 이력 길이


def _plain(row: dict) -> dict:
    """Decimal/date 를 프롬프트·JSON 직렬화 가능한 기본 타입으로 정규화한다."""

    out = {}
    for key, value in row.items():
        if value is None or isinstance(value, (int, str, float)):
            out[key] = value
        else:
            try:
                out[key] = float(value)  # Decimal
            except (TypeError, ValueError):
                out[key] = str(value)  # date 등
    return out


async def _load_supply_evidence(conn, candidate: Candidate) -> None:
    for edge in candidate.source_edges:  # select 가 gid 오름차순으로 넣었다
        if len(candidate.evidence) >= EVIDENCE_PER_CANDIDATE:
            break
        rows = await repository.fetch_edge_evidence(
            conn, edge.supplier_name, "SUPPLIES_TO", edge.root_name,
            limit=EVIDENCE_PER_EDGE,
        )
        for row in rows:
            if len(candidate.evidence) >= EVIDENCE_PER_CANDIDATE:
                break
            candidate.evidence.append(Evidence(
                type=row["source_type"],
                text=row["evidence"] or (row["item"] or ""),
                date=str(row["mentioned_at"]),
                link=row["link"],
                ref_id=row["id"],
            ))


def _load_theme_evidence(candidate: Candidate, news) -> None:
    # ① 트리거 원 뉴스 — 수혜 시나리오의 사건 근거는 트리거 호재 뉴스 그 자체.
    candidate.evidence.append(Evidence(
        type="news", text=news.title, date=news.published_at, link=news.link,
    ))
    # ② 테마 편입 사유 — 링크 없는 그래프 유래 근거. expand_theme 이 "[테마명] 사유"
    #    형태로 조립해 테마 귀속이 보존된다(스펙 §5.5).
    for reason in candidate.matched_reasons:
        candidate.evidence.append(Evidence(type="theme", text=reason))


async def collect_financials(state: GraphState) -> dict:
    news = state["news"]
    kept: list[Candidate] = []
    async with postgres_client.connection() as conn:
        for candidate in state["candidates"]:
            if candidate.track in ("supply", "both"):
                await _load_supply_evidence(conn, candidate)
            if candidate.track in ("theme", "both"):
                _load_theme_evidence(candidate, news)
            # 두 축 모두 빈손일 때만 제거한다 — both 후보가 공시 근거 부재로
            # 탈락하면 테마 근거를 가진 채 사라진다.
            if not candidate.evidence:
                logger.info("인용 가능한 근거 0건 후보 제거: %s", candidate.ticker)
                continue

            if candidate.company_id is not None:
                candidate.financials = [
                    _plain(row)
                    for row in await repository.fetch_financial_history(
                        conn, candidate.company_id, limit=FINANCIAL_YEARS
                    )
                ]
            valuation = await repository.fetch_latest_valuation(conn, candidate.ticker)
            candidate.valuation = _plain(valuation) if valuation else None
            kept.append(candidate)

    if not kept:
        return {"candidates": [], "status": "no_candidates",
                "reason": "후보들에서 인용 가능한 공시·뉴스 근거를 찾지 못했습니다."}
    return {"candidates": kept}

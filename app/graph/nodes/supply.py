"""supply_chain 에이전트 노드.

- collect_supply: 뉴스 관계의 subject company(앵커)를 ticker 로 특정 → Neo4j
  에서 유입 SUPPLIES_TO 1-hop 공급사 탐색(뉴스 당사자 제외) → 시장별
  (KOSPI/KOSDAQ) 시가총액 상위 3개씩 선별 → 근거(Postgres 원장)·연간 재무
  테이블(table RAG 원천) 적재. LLM 없음. 후보가 없으면 라우팅이 그래프를
  조기 종료한다.
- supply_judge: 패킹(관계·근거·재무 테이블) → 5단계 체크리스트 심사 →
  KOSPI 2 + KOSDAQ 2 추천 랭킹. 실패는 error 로 기록하고 그래프를 죽이지
  않는다.
"""

from __future__ import annotations

import logging
import time

from core import postgres_database
from graph.models import Candidate, Evidence
from graph.state import GraphState
from graph.utils import llm
from graph.utils.packer import pack_judge_context
from graph.utils.postprocess import validate_and_rank
from insights import repository

logger = logging.getLogger(__name__)

TOP_PER_MARKET = 3  # 시장(KOSPI/KOSDAQ)별로 시총 상위 몇 개를 심사에 올릴지
MARKETS = ("KOSPI", "KOSDAQ")  # 추천 대상 시장 — 그 외(KONEX 등)는 제외
EVIDENCE_PER_EDGE = 3
FINANCIAL_YEARS = 4  # table RAG 로 넣는 연간 재무 이력 길이


async def collect_supply(state: GraphState) -> dict:
    try:
        return await _collect_supply(state)
    except Exception as error:
        logger.exception("공급망 수집 실패")
        return {"anchors": [], "candidates": [], "items": [], "pool_size": 0, "error": str(error)}


async def _collect_supply(state: GraphState) -> dict:
    async with postgres_database.connection() as conn:
        anchors = await repository.fetch_anchors(conn, state["rep_news_id"])
        if not anchors:
            return {"anchors": [], "candidates": [], "items": [], "pool_size": 0}

        # 1) 뉴스 관계의 subject company(앵커)를 ticker 로 특정하고, Neo4j 에서
        #    그 기업에 공급하는(유입 SUPPLIES_TO) 1-hop 공급사를 찾는다.
        #    뉴스에 이미 등장한 당사자(subject·object 모두)는 후보에서 제외한다.
        parties = await repository.fetch_news_parties(conn, state["rep_news_id"])
        party_tickers = {p["subject_code"] for p in parties if p["subject_code"]} | {
            p["object_code"] for p in parties if p["object_code"]
        }

        by_ticker: dict[str, Candidate] = {}
        edges_by_ticker: dict[str, list[tuple[str, str]]] = {}
        exclude = sorted(party_tickers)
        for party in parties:
            subject_ticker = party["subject_code"]
            if subject_ticker is None:
                continue  # 비상장 subject 는 그래프에서 특정할 수 없다
            for row in await repository.fetch_supply_neighbors(subject_ticker, exclude):
                candidate = by_ticker.get(row["ticker"])
                if candidate is None:
                    candidate = Candidate(
                        ticker=row["ticker"],
                        name=row["name"],
                        company_id=row["company_id"],
                        relation_lines=[],
                        evidence=[],
                    )
                    by_ticker[row["ticker"]] = candidate
                    edges_by_ticker[row["ticker"]] = []
                edge = (row["subject_name"], row["object_name"])
                if edge not in edges_by_ticker[row["ticker"]]:
                    edges_by_ticker[row["ticker"]].append(edge)
                    candidate.disclosure_count += row["disclosure_count"]
                    candidate.relation_lines.append(
                        f"{row['subject_name']} → SUPPLIES_TO → {row['object_name']}"
                    )

        # 2) 시장(KOSPI/KOSDAQ)별 시가총액 상위 TOP_PER_MARKET 개씩 남긴다.
        #    시장이 그 외이거나 stocks 에 없는 종목은 추천 대상이 아니므로 버린다.
        #    한 시장의 후보가 그보다 적으면 있는 만큼 그대로 통과한다.
        if by_ticker:
            for row in await repository.fetch_market_info(conn, list(by_ticker)):
                candidate = by_ticker.get(row["ticker"])
                if candidate is not None:
                    candidate.market = row["market"]
                    if row["market_cap"] is not None:
                        candidate.market_cap = int(row["market_cap"])

        selected = []
        for market in MARKETS:
            pool = [c for c in by_ticker.values() if c.market == market]
            pool.sort(key=lambda c: -(c.market_cap or 0))
            selected.extend(pool[:TOP_PER_MARKET])

        # 3) 선별된 후보에만 근거(원장)·재무 테이블을 적재한다.
        for candidate in selected:
            for subject_name, object_name in edges_by_ticker[candidate.ticker]:
                evidence_rows = await repository.fetch_edge_evidence(
                    conn, subject_name, "SUPPLIES_TO", object_name, limit=EVIDENCE_PER_EDGE
                )
                candidate.evidence.extend(
                    Evidence(
                        type=row["source_type"],
                        text=row["evidence"] or (row["item"] or ""),
                        date=str(row["mentioned_at"]),
                        link=row["link"],
                        ref_id=row["id"],
                    )
                    for row in evidence_rows
                )

            if candidate.company_id is not None:
                candidate.financials = [
                    _plain(row)
                    for row in await repository.fetch_financial_history(
                        conn, candidate.company_id, limit=FINANCIAL_YEARS
                    )
                ]
            valuation = await repository.fetch_latest_valuation(conn, candidate.ticker)
            candidate.valuation = _plain(valuation) if valuation else None

    return {"anchors": anchors, "candidates": selected}


def _plain(row: dict) -> dict:
    """Decimal/date 를 프롬프트·JSON 직렬화 가능한 기본 타입으로 정규화한다."""

    out = {}
    for key, value in row.items():
        if value is None or isinstance(value, (int, str)):
            out[key] = value
        elif isinstance(value, float):
            out[key] = value
        else:
            try:
                out[key] = float(value)  # Decimal
            except (TypeError, ValueError):
                out[key] = str(value)  # date 등
    return out


async def supply_judge(state: GraphState) -> dict:
    started = time.monotonic()
    candidates = state["candidates"]
    packed = pack_judge_context(state["news"], state["anchors"], candidates)
    try:
        judge_output = await llm.judge_supply(packed.prompt)
    except Exception as error:
        logger.exception("공급망 심사 실패")
        return {"items": [], "pool_size": len(candidates), "error": str(error)}

    items = validate_and_rank(judge_output, packed.by_cid, packed.known_eids)
    logger.info(
        "supply_judge: %.1fs (후보 %d → 추천 %d)",
        time.monotonic() - started,
        len(candidates),
        len(items),
    )
    return {
        "items": items,
        "pool_size": len(candidates),
        "event_interpretation": judge_output.event_interpretation,
        "raw": judge_output.model_dump(),
    }

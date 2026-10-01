"""호재 theme 트랙 — expand_theme(벡터 검색, LLM 없음) / filter_theme(LLM#2).

시나리오 probe 마다 BELONGS_TO.reason 임베딩을 검색해 기업을 직접 회수하고
티커 기준으로 병합한다(스펙 §5).

배제는 derive_exclusions 가 주는 것(루트 기업 자신 + relation_lines 당사자)만
쓴다 — 악재 트랙이 하던 밸류체인 1-hop 배제는 하지 않는다. 호재에서 루트의
공급사는 동반 피해자가 아니라 가장 확실한 수혜자이고, supply 트랙과의 교집합이
가장 강한 신호이기 때문이다(스펙 §5.7).
"""

from __future__ import annotations

import asyncio
import logging

from beneficiary import repository
from beneficiary.models import ScenarioProbe, ThemeCandidate
from beneficiary.agent.nodes.common import derive_exclusions
from beneficiary.agent.subgraphs.theme.state import ThemeTrackState
from beneficiary.agent.utils import embed, llm
from beneficiary.agent.utils.packer import pack_theme_filter_context
from beneficiary.agent.utils.postprocess import apply_filter_output

logger = logging.getLogger(__name__)

THEME_HITS_PER_PROBE = 30
THEME_OVERFETCH = 150  # 인덱스 top-k 뒤에 필터가 걸리므로 과다 조회한다
COMPANY_POOL_CAP = 10  # 간선들을 기업별로 묶었을 때 올리는 최대 기업 수 — LLM#2 입력 보호
MIN_SCORE = 0.62
WEAK_MARGIN = 0.06
MATCHED_THEMES_CAP = 5 # 각 기업 당 병합 시 누적될 테마 개수 
MATCHED_REASONS_CAP = 3 # 각 기업 당 병합 시 누적될 테마 편입 사유 개수


def _union_capped(base: list[str], extra: list[str], cap: int) -> list[str]:
    return list(dict.fromkeys([*base, *extra]))[:cap]


def merge_theme_rows(
    rows_by_probe: list[tuple[ScenarioProbe, list[dict]]],
) -> list[ThemeCandidate]:
    """
    검색된 간선들을 모아 기업별로 묶어서 올린다

    probe 간 티커 병합 — 최고 score 를 준 probe 의 stage·hypothesis 를 승계한다.

    동점이면 stage 가 낮은 쪽(직접 수혜)이 이긴다. reason 은 "[테마명] 사유"
    형태로 조립해 테마 귀속을 evidence 텍스트에 보존한다(스펙 §5.5).
    tid 는 병합·절단 후에 부여한다.
    """

    by_ticker: dict[str, ThemeCandidate] = {}
    for probe, rows in rows_by_probe:
        for row in rows:
            reason_text = f"[{row['theme_name']}] {row['reason']}"
            existing = by_ticker.get(row["ticker"])
            if existing is None:
                by_ticker[row["ticker"]] = ThemeCandidate(
                    tid=None,
                    stage=probe.stage,
                    hypothesis=probe.hypothesis,
                    ticker=row["ticker"],
                    name=row["name"],
                    company_id=row["company_id"],
                    market=row["market"],
                    score=row["score"],
                    matched_themes=[row["theme_name"]],
                    matched_reasons=[reason_text],
                )
                continue
            better = (row["score"], -probe.stage) > (existing.score, -existing.stage)
            if better:
                existing.score = row["score"]
                existing.stage = probe.stage
                existing.hypothesis = probe.hypothesis
            existing.matched_themes = _union_capped(
                existing.matched_themes, [row["theme_name"]], MATCHED_THEMES_CAP
            )
            existing.matched_reasons = _union_capped(
                existing.matched_reasons, [reason_text], MATCHED_REASONS_CAP
            )
    return list(by_ticker.values())


def truncate_and_assign_tids(candidates: list[ThemeCandidate]) -> list[ThemeCandidate]:
    """
    후보 기업들로 선정된 list[ThemeCandidate]을 stage, score를 기준으로 정렬
    정렬하며 고유 번호(index)를 부여
    """

    candidates = sorted(candidates, key=lambda c: (c.stage, -c.score, c.ticker))
    if len(candidates) > COMPANY_POOL_CAP:
        logger.info("테마 후보 절단: %d → %d", len(candidates), COMPANY_POOL_CAP)
        candidates = candidates[:COMPANY_POOL_CAP]
    for index, candidate in enumerate(candidates, start=1):
        candidate.tid = f"t{index:02d}"
    return candidates


async def expand_theme(state: ThemeTrackState) -> dict:
    """
    expand_theme으로 planner가 생성한 질의 쿼리를 바탕으로 테마 조회
    테마 조회 후 기업 ticker를 기준으로 병합
    """

    probes = state["plan"].scenario_probes
    exclude_names, exclude_tickers = derive_exclusions(
        state["root_companies"], state["relation_lines"]
    )
    names, tickers = sorted(exclude_names), sorted(exclude_tickers)

    # planner가 제시한 쿼리 임베딩
    vectors = await embed.embed_queries([probe.query.strip() for probe in probes])

    # 관련 테마 검색 병렬처리
    rows_per_probe = await asyncio.gather(*(
        repository.search_theme_reasons(
            query_vector=vector, exclude_names=names, exclude_tickers=tickers,
            min_score=MIN_SCORE, limit=THEME_HITS_PER_PROBE, over_fetch=THEME_OVERFETCH,
        )
        for vector in vectors
    ))

    raw_total = sum(len(rows) for rows in rows_per_probe)

    # 기업을 기준으로 묶고 고유 id 부여
    candidates = truncate_and_assign_tids(
        merge_theme_rows(list(zip(probes, rows_per_probe)))
    )

    logger.info(
        "테마 검색: probe %d개 → 필터 통과 %d행 (임계값 %.2f + 시장·상장·제외·상한)"
        " → 병합 후 %d개",
        len(probes), raw_total, MIN_SCORE, len(candidates),
    )
    return {"candidates": candidates}


async def filter_theme(state: ThemeTrackState) -> dict:
    """
    expand_themes 이후 items를 기반으로 strong/medium/weak 판정을 내린다.
    """

    # expand_themes 이후 반환된 기업 조회
    candidates = state["candidates"]

    output = await llm.filter_theme(pack_theme_filter_context(state["plan"], candidates))
    # 임계값 언저리 후보는 strong 금지 — 유사도가 supplied_items 의 역할을 대신한다.
    cap_weak_ids = {c.tid for c in candidates if c.score < MIN_SCORE + WEAK_MARGIN}
    strong_ids, weak_ids = apply_filter_output(
        output, {c.tid: c for c in candidates}, cap_weak_ids
    )
    return {"candidates": candidates, "strong_ids": strong_ids, "weak_ids": weak_ids}

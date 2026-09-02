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
from beneficiary.agent.tracks.theme.state import ThemeTrackState
from beneficiary.agent.utils import embed, llm
from beneficiary.agent.utils.packer import pack_theme_filter_context
from beneficiary.agent.utils.postprocess import apply_filter_output

logger = logging.getLogger(__name__)

THEME_HITS_PER_PROBE = 30
THEME_OVERFETCH = 150  # 인덱스 top-k 뒤에 필터가 걸리므로 과다 조회한다
THEME_POOL_CAP = 60  # 병합 후 총량 — LLM#2 입력 보호
# 라이브 인덱스 실측으로 확정한 값이다(Task 6 후 측정). Neo4j 는 코사인을
# (1+cos)/2 로 정규화하고 Titan v2 는 normalize=True 라, 실제 점수는 0.63~0.77
# 의 좁은 띠에 몰린다 — true positive 0.68~0.77, 인접하나 직접성 약함 0.63~0.67.
# 따라서 MIN_SCORE 는 명백한 무관만 걷어내는 바닥이고, 의미 판정은 filter_theme
# LLM 이 한다. WEAK_MARGIN 은 strong 하한을 0.68 로 놓아 그 경계에 맞춘 값이다.
MIN_SCORE = 0.62
WEAK_MARGIN = 0.06
MATCHED_THEMES_CAP = 5
MATCHED_REASONS_CAP = 3


def _union_capped(base: list[str], extra: list[str], cap: int) -> list[str]:
    return list(dict.fromkeys([*base, *extra]))[:cap]


def merge_theme_rows(
    rows_by_probe: list[tuple[ScenarioProbe, list[dict]]],
) -> list[ThemeCandidate]:
    """probe 간 티커 병합 — 최고 score 를 준 probe 의 stage·hypothesis 를 승계한다.

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


def truncate_and_assign_tids(hits: list[ThemeCandidate]) -> list[ThemeCandidate]:
    """정렬(stage asc → score desc → ticker asc)·절단(60)·tid 부여 — 전부 결정적.

    stage 를 첫 키로 두는 이유: 논리 사슬이 긴 2차 후보가 우연히 높은 유사도로
    1차를 앞서면 신뢰도 순서가 뒤집힌다(스펙 §5.5).
    """

    hits = sorted(hits, key=lambda h: (h.stage, -h.score, h.ticker))
    if len(hits) > THEME_POOL_CAP:
        logger.info("테마 후보 절단: %d → %d", len(hits), THEME_POOL_CAP)
        hits = hits[:THEME_POOL_CAP]
    for index, hit in enumerate(hits, start=1):
        hit.tid = f"t{index:02d}"
    return hits


async def expand_theme(state: ThemeTrackState) -> dict:
    probes = state["plan"].scenario_probes
    exclude_names, exclude_tickers = derive_exclusions(
        state["root_companies"], state["relation_lines"]
    )
    names, tickers = sorted(exclude_names), sorted(exclude_tickers)

    # normalize_plan 은 dedup 키로 strip() 된 query 를 쓰지만 probe 자체는
    # 원본(패딩 공백 포함)을 그대로 저장한다 — 임베딩에 넘기기 전 여기서 벗긴다.
    vectors = await embed.embed_queries([probe.query.strip() for probe in probes])

    # probe 별 검색은 서로 독립이다 — 순차 await 하지 않는다.
    rows_per_probe = await asyncio.gather(*(
        repository.search_theme_reasons(
            query_vector=vector, exclude_names=names, exclude_tickers=tickers,
            min_score=MIN_SCORE, limit=THEME_HITS_PER_PROBE, over_fetch=THEME_OVERFETCH,
        )
        for vector in vectors
    ))

    raw_total = sum(len(rows) for rows in rows_per_probe)
    hits = truncate_and_assign_tids(merge_theme_rows(list(zip(probes, rows_per_probe))))
    # 벡터 검색은 실패가 조용하다 — 회수 0이 "질의가 빗나갔다"인지 "그래프에
    # 아무것도 없다"인지 구분할 단서를 남긴다(스펙 §4.4·§5.5).
    # raw_total 은 임계값만의 통계가 아니다: Cypher 가 임계값·시장·상장·제외
    # 목록·LIMIT 을 한 번에 걸어 반환한 행 수다. 임계값 단독 통과 수는 여기서
    # 알 수 없으므로 그렇게 읽히지 않게 이름을 붙인다.
    logger.info(
        "테마 검색: probe %d개 → 필터 통과 %d행 (임계값 %.2f + 시장·상장·제외·상한)"
        " → 병합 후 %d개",
        len(probes), raw_total, MIN_SCORE, len(hits),
    )
    return {"hits": hits}


async def filter_theme(state: ThemeTrackState) -> dict:
    """LLM#2(테마 트랙) — 시나리오 가설과 편입 사유를 대조해 선별한다.

    실패는 서브그래프의 error_handler 가 outcome.error 로 강등한다.
    """

    hits = state["hits"]
    output = await llm.filter_theme(pack_theme_filter_context(state["plan"], hits))
    # 임계값 언저리 후보는 strong 금지 — 유사도가 supplied_items 의 역할을 대신한다.
    cap_weak_ids = {hit.tid for hit in hits if hit.score < MIN_SCORE + WEAK_MARGIN}
    strong_ids, weak_ids = apply_filter_output(
        output, {hit.tid: hit for hit in hits}, cap_weak_ids
    )
    return {"hits": hits, "strong_ids": strong_ids, "weak_ids": weak_ids}

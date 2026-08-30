"""컨텍스트 패킹 — 후보 카드(관계·근거·재무 테이블) 렌더링과 cid/eid 부여.

여기서 부여한 id 집합이 후처리 검증의 기준(known_eids/by_cid)이 된다.
"""

from __future__ import annotations

from graph.models import Anchor, Candidate, NewsContext, PackedContext


def _news_block(news: NewsContext) -> list[str]:
    summary = news.summary or ""
    return [f"[뉴스] {news.title} / {summary} / {news.published_at or '보도일 미상'}"]


def _anchor_block(anchors: list[Anchor]) -> list[str]:
    lines: list[str] = []
    for anchor in anchors:
        ticker = f"({anchor.ticker})" if anchor.ticker else "(비상장)"
        lines.append(f"[사건 앵커] {anchor.name}{ticker}: {anchor.description or ''}")
    return lines


def _num(value) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _financial_block(candidate: Candidate) -> list[str]:
    if not candidate.financials:
        return ["  [재무] (데이터 없음)"]

    lines = ["  [재무 — 연간(연결), 최신 회계연도부터]"]
    lines.append("  회계연도 | 매출액 | 영업이익 | 순이익 | ROE(%) | EPS | 부채비율(%) | 자기자본")
    for row in candidate.financials:
        lines.append(
            "  {fy} | {rev} | {op} | {ni} | {roe} | {eps} | {debt} | {eq}".format(
                fy=row.get("fiscal_yymm", "-"),
                rev=_num(row.get("revenue")),
                op=_num(row.get("operating_income")),
                ni=_num(row.get("net_income")),
                roe=row.get("roe") if row.get("roe") is not None else "-",
                eps=_num(row.get("eps")),
                debt=row.get("debt_ratio") if row.get("debt_ratio") is not None else "-",
                eq=_num(row.get("total_equity")),
            )
        )
    if candidate.valuation:
        v = candidate.valuation
        lines.append(
            f"  [밸류에이션 {v.get('trade_date')}] PER {v.get('per') or '-'} / "
            f"PBR {v.get('pbr') or '-'} / 시가총액 {_num(v.get('market_cap'))}"
        )
    return lines


def pack_judge_context(
    news: NewsContext,
    anchors: list[Anchor],
    candidates: list[Candidate],
) -> PackedContext:
    lines = _news_block(news) + _anchor_block(anchors) + [""]

    by_cid: dict[str, Candidate] = {}
    known_eids: set[str] = set()
    eid_seq = 0

    for index, candidate in enumerate(candidates, start=1):
        cid = f"c{index:02d}"
        candidate.cid = cid
        by_cid[cid] = candidate

        lines.append(
            f"[후보 {cid}] {candidate.name} ({candidate.ticker}, "
            f"{candidate.market or '시장 미상'}) — 시총 {_num(candidate.market_cap)} / "
            f"공시 {candidate.disclosure_count}건"
        )
        lines.extend(f"  {line}" for line in candidate.relation_lines)

        for evidence in candidate.evidence:
            eid_seq += 1
            eid = f"e{eid_seq:02d}"
            evidence.eid = eid
            known_eids.add(eid)
            source = f"({evidence.type} {evidence.date})" if evidence.date else f"({evidence.type})"
            lines.append(f"  [{eid}] {source} {evidence.text}")

        lines.extend(_financial_block(candidate))
        lines.append("")

    return PackedContext(prompt="\n".join(lines), by_cid=by_cid, known_eids=known_eids)

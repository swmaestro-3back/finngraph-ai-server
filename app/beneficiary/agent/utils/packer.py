"""beneficiary 컨텍스트 패킹 — LLM 3회 각각의 입력 렌더링.

pack_evaluator_context 가 부여한 cid/eid 집합이 후처리 검증의 기준이다.
v2 는 eid 를 후보별 스코프(eids_by_cid)로 관리한다 — 심사가 남의 근거로
접지되는 구멍을 막는다(스펙 §4.8). 형식 변경 시 PROMPT_VERSION 인상.
"""

from __future__ import annotations

from beneficiary.models import (
    RootCompany,
    Candidate,
    SupplyChainCandidate,
    NewsContext,
    NewsPlan,
    PackedContext,
    RelationLine,
)

SHOWN_ITEMS_CAP = 10  # 한 줄에 노출하는 아이템 수 상한
DESCRIPTION_CAP = 100  # 테마 설명 요약 길이

TRACK_LABELS = {"supply": "공급", "rival": "경쟁"}


def _news_block(news: NewsContext) -> list[str]:
    summary = news.summary or ""
    return [f"[뉴스] {news.title} / {summary} / {news.published_at or '보도일 미상'}"]


def _plan_block(plan: NewsPlan) -> list[str]:
    items = ", ".join(plan.core_items) if plan.core_items else "(없음)"
    return [f"[사건 계획] {plan.event_summary} / 극성: {plan.polarity} / 핵심 아이템: {items}"]


def _num(value) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _items_inline(items: list[str]) -> str:
    if not items:
        return "(없음)"
    return ", ".join(items[:SHOWN_ITEMS_CAP])


# ── LLM#1: 계획 ──────────────────────────────────────────────────────────────


def pack_plan_context(
    news: NewsContext,
    root_companies: list[RootCompany],
    relation_lines: list[RelationLine],
    themes_by_root: dict[str, list[dict]],
) -> str:
    lines = _news_block(news)
    for root in root_companies:  # 루트 기업은 상장 국내 기업만 (ticker 보장)
        lines.append(f"[루트 기업] {root.name}({root.ticker}): {root.description or ''}")
        themes = themes_by_root.get(root.name)
        if themes:
            for theme in themes:
                desc = (theme.get("description") or "")[:DESCRIPTION_CAP]
                lines.append(f"  - 테마: {theme['name']} ({desc})")
        else:
            lines.append("  - 테마: (없음)")
    lines.append("")
    lines.append("[관계 라인 — 전 극성. denied/terminated 는 끊긴 관계다]")
    for rl in relation_lines:
        impact = f"subject_impact={rl.subject_impact or '-'} object_impact={rl.object_impact or '-'}"
        lines.append(
            f"- {rl.subject_name} -{rl.relation}-> {rl.object_name}"
            f" | item: {rl.item or '(없음)'} | polarity: {rl.polarity or 'affirmed'} | {impact}"
        )
    return "\n".join(lines)


# ── LLM#2: 선별 ──────────────────────────────────────────────────────────────


def pack_supply_filter_context(plan: NewsPlan, edges: list[SupplyChainCandidate]) -> str:
    lines = _plan_block(plan) + [""]
    for edge in edges:
        items = _items_inline(list(dict.fromkeys([*edge.disclosure_items, *edge.news_items])))
        lines.append(
            f"[{edge.gid}] (루트: {edge.root_name}) {edge.subject_name} →공급→ {edge.object_name}"
            f" | items: {items} | 공시{edge.disclosure_count}·뉴스{edge.news_mention_count}"
        )
    return "\n".join(lines)


# ── LLM#3: 심사 ──────────────────────────────────────────────────────────────


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


def pack_evaluator_context(
    news: NewsContext,
    root_companies: list[RootCompany],
    plan: NewsPlan,
    candidates: list[Candidate],
) -> PackedContext:
    lines = _news_block(news) + _plan_block(plan)
    for root in root_companies:
        lines.append(f"[사건 루트 기업] {root.name}({root.ticker}): {root.description or ''}")
    lines.append("")

    by_cid: dict[str, Candidate] = {}
    eids_by_cid: dict[str, set[str]] = {}
    eid_seq = 0

    for index, candidate in enumerate(candidates, start=1):
        cid = f"c{index:02d}"
        candidate.cid = cid
        by_cid[cid] = candidate
        eids_by_cid[cid] = set()

        grade = candidate.relevance + ("(승격)" if candidate.promoted else "")
        lines.append(
            f"[후보 {cid}] {candidate.name} ({candidate.ticker}, "
            f"{candidate.market or '시장 미상'})"
            f" / 트랙 {TRACK_LABELS[candidate.track]} / 등급 {grade}"
            f" / 매칭 아이템: {_items_inline(candidate.matched_items)}"
        )
        lines.extend(f"  {line}" for line in candidate.relation_lines)

        for evidence in candidate.evidence:
            eid_seq += 1
            eid = f"e{eid_seq:02d}"
            evidence.eid = eid
            eids_by_cid[cid].add(eid)
            source = f"({evidence.type} {evidence.date})" if evidence.date else f"({evidence.type})"
            link = f" {evidence.link}" if evidence.link else ""
            lines.append(f"  [{eid}] {source} {evidence.text}{link}")

        lines.extend(_financial_block(candidate))
        lines.append("")

    return PackedContext(prompt="\n".join(lines), by_cid=by_cid, eids_by_cid=eids_by_cid)

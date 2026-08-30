"""workflow 내 llm의 structured_output 및 workflow 내에서 사용될 pydantic model들.

pydantic 모델은 LLM 구조화 출력(with_structured_output) 계약이고, dataclass 는
노드 사이를 오가는 내부 전달용이다. API 응답 모델은 insights/models.py 에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

# ── 워크플로우 내부 전달용 ────────────────────────────────────────────────────


@dataclass
class NewsContext:
    title: str
    summary: str | None
    published_at: str | None


@dataclass
class Anchor:
    company_id: int | None  # 비상장·해외 당사자는 companies 에 없을 수 있다
    name: str
    ticker: str | None
    description: str | None


@dataclass
class Evidence:
    type: str  # disclosure | news
    text: str
    date: str | None = None
    link: str | None = None
    ref_id: int | None = None  # relation_sources.id 등 원장 참조
    eid: str | None = None  # 패킹 시 부여되는 [eNN]


@dataclass
class Candidate:
    ticker: str
    name: str
    company_id: int | None
    relation_lines: list[str]
    evidence: list[Evidence]
    disclosure_count: int = 0  # 관계 강도 참고치 (선별 기준 아님)
    market: str | None = None  # KOSPI/KOSDAQ — 시장별 상위 3개 선별 기준
    market_cap: int | None = None  # 최신 시가총액 — 시장 내 정렬 기준
    financials: list[dict] = field(default_factory=list)  # 연간 재무 이력 (table RAG)
    valuation: dict | None = None  # 최신 PER 등 밸류에이션
    cid: str | None = None  # 패킹 시 부여되는 cNN


@dataclass
class PackedContext:
    prompt: str
    by_cid: dict[str, Candidate]
    known_eids: set[str] = field(default_factory=set)


@dataclass
class RankedItem:
    """심사 출력을 후처리(검증·랭킹)한 결과 — 서비스 계층이 소비한다."""

    candidate: Candidate
    impact: str
    confidence: str
    rationale: str
    caveats: str | None
    evidence_ids: list[str]
    rank: int = 0


# ── LLM 구조화 출력 ──────────────────────────────────────────────────────────


class JudgeInsight(BaseModel):
    candidate_id: str
    impact: Literal["benefit", "damage", "neutral"] = Field(
        description="benefit 또는 damage만 여기에 넣는다. neutral 후보는 "
        "insights가 아니라 no_impact_ids에 id만 넣는다."
    )
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(description="한국어 1~2문장. 반드시 근거 id([eNN])를 인용한다.")
    evidence_ids: list[str] = []
    caveats: str | None = None


class JudgeOutput(BaseModel):
    event_interpretation: str
    insights: list[JudgeInsight] = []
    no_impact_ids: list[str] = []

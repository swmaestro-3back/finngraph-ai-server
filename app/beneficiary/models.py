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
    link: str | None = None  # 악재 트랙의 트리거 뉴스 근거


@dataclass
class RootCompany:
    """상장 국내 기업만 루트 기업다 — 해외·비상장 subject 는 build_plan 이 걸러낸다."""

    company_id: int
    name: str
    ticker: str
    description: str | None


@dataclass
class RelationLine:
    """뉴스(클러스터)가 서술한 관계 라인 — 전 극성 (LLM 은 해지·부인 맥락도 본다)."""

    subject_name: str
    subject_code: str | None
    relation: str
    object_name: str
    object_code: str | None
    item: str | None
    polarity: str | None  # affirmed / denied / terminated / NULL(=affirmed 취급)
    subject_impact: str | None  # positive / negative / neutral / NULL
    object_impact: str | None


@dataclass
class SupplyChainCandidate:
    """호재 트랙 원시 후보 — 유입 SUPPLIES_TO 간선 하나."""

    gid: str | None  # 총량 절단 후 부여되는 gNN
    root_name: str
    subject_name: str  # 공급사(후보) 정규명
    object_name: str  # 루트 기업 정규명
    ticker: str
    name: str
    company_id: int | None
    market: str | None = None
    disclosure_items: list[str] = field(default_factory=list)
    news_items: list[str] = field(default_factory=list)
    disclosure_count: int = 0
    news_mention_count: int = 0
    last_mentioned_at: str | None = None
    relevance: str | None = None  # None | strong | weak | irrelevant
    root_index: int = 0  # 루트 기업 순 정렬용 내부 값 (fetch_root_companies 순서)


@dataclass
class RivalCandidate:
    """악재 트랙 원시 후보 — 테마 겹침 경쟁사 (probe 간 티커 병합 후 1건)."""

    kid: str | None  # 병합·절단 후 부여되는 kNN
    subject_name: str  # 최대 shared_themes 를 준 probe 의 루트 기업
    ticker: str
    name: str
    company_id: int | None
    market: str | None = None
    shared_themes: int = 0
    via_themes: list[str] = field(default_factory=list)  # 상한 5
    reasons: list[str] = field(default_factory=list)  # 테마 편입 사유, 상한 3
    supplied_items: list[str] = field(default_factory=list)  # 유출 간선 아이템, 상한 10
    relevance: str | None = None


@dataclass
class Evidence:
    type: str  # disclosure | news | theme
    text: str
    date: str | None = None
    link: str | None = None
    ref_id: int | None = None  # relation_sources.id 등 원장 참조
    eid: str | None = None  # 패킹 시 부여되는 [eNN]


@dataclass
class Candidate:
    """심사 풀에 오른 확정 후보 (기업 단위)."""

    ticker: str
    name: str
    company_id: int | None
    track: Literal["supply", "rival"]
    relation_lines: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    matched_items: list[str] = field(default_factory=list)  # 상한 5
    relevance: str = "strong"  # 원 등급 — 승격돼도 유지
    promoted: bool = False  # 쿼터 미달로 weak 에서 승격됐는가
    via_themes: list[str] = field(default_factory=list)  # rival 전용
    reasons: list[str] = field(default_factory=list)  # rival 전용 — finance_collector 근거 재료
    source_edges: list[SupplyChainCandidate] = field(default_factory=list)  # supply 전용, gid 오름차순
    market: str | None = None
    financials: list[dict] = field(default_factory=list)
    valuation: dict | None = None
    cid: str | None = None


@dataclass
class PackedContext:
    prompt: str
    by_cid: dict[str, Candidate]
    eids_by_cid: dict[str, set[str]] = field(default_factory=dict)  # v2: 후보별 eid 스코프


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


class RivalProbe(BaseModel):
    subject_name: str = Field(description="제시된 상장 루트 기업 목록 안의 정규명 그대로")
    themes: list[str] = Field(default=[], description="그 루트 기업의 테마 목록 안에서 사건 관련 1~3개")


class NewsPlan(BaseModel):
    event_summary: str = Field(description="사건 해석 1~2문장, 한국어")
    polarity: Literal["positive", "negative"]
    core_items: list[str] = Field(default=[], description="뉴스에 실제 등장한 품목·기술 명사구 1~5개")
    rival_probes: list[RivalProbe] = Field(default=[], description="negative 일 때만 채운다")


class FilterOutput(BaseModel):
    strong: list[str] = []
    weak: list[str] = []


class EvaluatorInsight(BaseModel):
    candidate_id: str
    impact: Literal["benefit"] = Field(
        description="수혜(benefit)만 여기에 넣는다. 수혜가 아니면 insights 가 아니라 no_impact_ids 에 id 만 넣는다."
    )
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(description="한국어 1~2문장. 반드시 근거 id([eNN])를 인용한다.")
    evidence_ids: list[str] = []
    caveats: str | None = None


class EvaluatorOutput(BaseModel):
    event_interpretation: str
    insights: list[EvaluatorInsight] = []
    no_impact_ids: list[str] = []

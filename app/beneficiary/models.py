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
    link: str | None = None  # 트리거 뉴스 근거


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
class SubgraphResult:
    """
    status 는 정상 조기 종료(no_pool | no_candidates), error 는 장애다.
    둘 다 None 이면 정상이다 — 부모는 이 값을 예외가 아니라 값으로 받는다.
    """

    status: str | None = None
    reason: str | None = None
    error: str | None = None

@dataclass
class SupplyEdgeCandidate:
    """supply 트랙 원시 후보 (간선 단위) — 유입 SUPPLIES_TO 간선 하나.

    LLM#2 의 판정 단위다: 납품 품목은 (공급사, 루트) 쌍마다 다르므로 여기서
    등급을 매기고, merge_edges_by_company 가 티커로 병합해 SupplyCandidate
    (기업 단위)를 만든다.
    """

    gid: str | None  # 총량 절단 후 부여되는 gNN
    root_name: str  # 루트 기업 정규명 — 간선의 object 쪽
    supplier_name: str  # 공급사(후보) 정규명 — 간선의 subject 쪽
    supplier_ticker: str
    supplier_id: int | None
    supplier_market: str | None = None
    disclosure_items: list[str] = field(default_factory=list)
    news_items: list[str] = field(default_factory=list)
    disclosure_count: int = 0
    news_mention_count: int = 0
    last_mentioned_at: str | None = None
    relevance: str | None = None  # None | strong | weak | irrelevant
    root_index: int = 0  # 루트 기업 순 정렬용 내부 값 (fetch_root_companies 순서)

@dataclass
class SupplyCandidate:
    """supply 트랙 원시 후보 (기업 단위) — 판정이 끝난 간선을 티커로 병합한 것.

    edges 는 이 기업의 등급을 만든 구성 간선이다(gid 오름차순): strong 간선이
    하나라도 있으면 strong 간선만 남고, 없으면 weak 간선이 들어온다. 등급을
    흐리는 간선은 병합 단계에서 빠진다.
    """

    ticker: str
    name: str
    company_id: int | None
    market: str | None
    relevance: str  # strong | weak — irrelevant 만 남은 기업은 병합에서 사라진다
    edges: list[SupplyEdgeCandidate] = field(default_factory=list)


@dataclass
class SupplySubgraphResult(SubgraphResult):
    """supply 서브그래프가 부모에 올리는 것 전부 — 원시 후보 + 종료 신호."""

    candidates: list[SupplyCandidate] = field(default_factory=list)


@dataclass
class ThemeCandidate:
    """호재 theme 트랙 원시 후보 — reason 벡터 검색 히트 (티커 병합 후 1건)."""

    tid: str | None
    stage: int
    hypothesis: str
    ticker: str
    name: str
    company_id: int | None
    market: str | None = None
    score: float = 0.0  # 최고 유사도
    matched_themes: list[str] = field(default_factory=list)  # 상한 5
    matched_reasons: list[str] = field(default_factory=list)  # 상한 3 — evidence 원문
    relevance: str | None = None  # None | strong | weak | irrelevant

@dataclass
class ThemeSubgraphResult(SubgraphResult):
    """theme 서브그래프가 부모에 올리는 것 전부 — 원시 후보 + 종료 신호."""

    candidates: list[ThemeCandidate] = field(default_factory=list)


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
    track: Literal["supply", "theme", "both"]
    relation_lines: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    matched_items: list[str] = field(default_factory=list)  # 상한 5
    relevance: str = "strong"  # 원 등급 — 승격돼도 유지
    promoted: bool = False  # 쿼터 미달로 weak 에서 승격됐는가
    source_edges: list[SupplyEdgeCandidate] = field(default_factory=list)  # supply 전용, gid 오름차순
    market: str | None = None
    financials: list[dict] = field(default_factory=list)
    valuation: dict | None = None
    cid: str | None = None

    # theme·both 전용
    hypothesis: str | None = None
    stage: int | None = None
    theme_score: float | None = None
    matched_themes: list[str] = field(default_factory=list)
    matched_reasons: list[str] = field(default_factory=list)


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
    caveats: str
    evidence_ids: list[str]
    rank: int = 0


# ── LLM Structured Output ──────────────────────────────────────────────────────────


class ScenarioProbe(BaseModel):
    stage: Literal[1, 2] = Field(
        description="1=사건의 직접 수혜, 2=그 수혜에서 파생되는 2차 수요"
    )
    hypothesis: str = Field(
        description="이 단계의 수혜 논리 한국어 3~4문장 — 사건이 만든 수요가 무엇이고, "
                    "어떤 경로로 이 단계까지 전달되며, 그 결과 어떤 제품·기술·역량의 "
                    "수요가 생기는지까지 쓴다"
    )
    query: str = Field(description="테마 편입 이유와 매칭될 검색 문구 — 명사구 중심, 기업명 금지")


class NewsPlan(BaseModel):
    event_summary: str = Field(
        description="탐색·선별 단계가 기준으로 쓸 사건 해석 1~2문장, 한국어. "
                    "사용자에게 보이지 않는다 — 응답의 서두는 심사 뒤에 쓰이는 "
                    "EvaluatorOutput.event_interpretation 이다."
    )
    polarity: Literal["positive", "negative"]
    demand_shift: str = Field(
        default="",
        description="이 사건이 만드는 지출·수요가 무엇이고 그 돈이 어떤 종류의 기업에 "
                    "도달하는지 2~3문장, 한국어. 두 선별 단계가 공유하는 판정 축이다 — "
                    "품목 목록(core_items)이 같아도 사건 종류(증설·수주·가격 급등)에 따라 "
                    "수혜자가 달라지는 것을 여기서 가른다. 기업명은 넣지 않는다."
    )
    certainty: str = Field(
        default="",
        description="사건의 확정성과 시점 1문장, 한국어 — 계약·공시로 확정인지, MOU·검토·"
                    "계획 단계인지, 언제 집행되는지. 수혜 시점과 실현 여부의 한계로 "
                    "사용자에게 전달된다."
    )
    core_items: list[str] = Field(default=[], description="뉴스에 실제 등장한 품목·기술 명사구 1~5개")
    scenario_probes: list[ScenarioProbe] = Field(default=[], description="positive 일 때만 채운다")


class FilterOutput(BaseModel):
    strong: list[str] = []
    weak: list[str] = []


class EvaluatorInsight(BaseModel):
    """심사 결과 한 건 — rationale·caveats 는 그대로 사용자에게 노출된다."""

    candidate_id: str
    impact: Literal["benefit"] = Field(
        description="수혜(benefit)만 여기에 넣는다. 수혜가 아니면 insights 가 아니라 no_impact_ids 에 id 만 넣는다."
    )
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(
        description="사용자가 그대로 읽는 한국어 4~5문장, 「~입니다/~합니다」체의 이어지는 "
                    "한 문단. 사건이 만든 수요가 이 기업에 닿는 경로를 이 기업에 맞게 다시 "
                    "쓴 문장으로 시작하고(가설 원문 복사 금지), 근거의 내용(품목명·공시 "
                    "날짜·수치)과 재무·밸류에이션을 그 문단 안에서 이어 쓴다. 근거 "
                    "id([eNN])·순위 언급·파이프라인 용어는 쓰지 않는다."
    )
    evidence_ids: list[str] = Field(
        default=[],
        description="이 판단이 실제로 쓴 근거의 id([eNN]) — 본문이 아니라 여기에만 넣는다. "
                    "응답의 근거 목록이 이 값으로 만들어진다."
    )
    caveats: str = Field(
        description="사용자가 그대로 읽는 한국어 4~5문장의 한계·유보, 「~입니다/~합니다」체의 "
                    "이어지는 한 문단. 투자 판단에 필요한 정보만 쓴다 — 파이프라인 내부 "
                    "사정과 순위는 쓰지 않는다."
    )


class EvaluatorOutput(BaseModel):
    """심사 결과 전체 — event_interpretation 은 응답의 서두로 그대로 노출된다."""

    event_interpretation: str = Field(
        description="사용자가 그대로 읽는 한국어 2~3문장의 서두, 「~입니다/~합니다」체. "
                    "사건이 만든 수요가 무엇이고 추천 기업들이 그 수요의 어디에 있는지를 "
                    "쓴다. 탐색 전에 쓰인 [사건 계획]의 요약을 되풀이하지 않는다. "
                    "종목명은 넣지 않는다."
    )
    insights: list[EvaluatorInsight] = []
    no_impact_ids: list[str] = []

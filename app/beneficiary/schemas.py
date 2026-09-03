"""beneficiary API 응답 모델 — HTTP 직렬화 계약.

이 모델의 형태 변경은 PROMPT_VERSION 인상과 함께 한다(응답 메타데이터로
버전이 노출되므로 소비자가 형태 변화를 감지할 수 있게).
"""

from __future__ import annotations

from pydantic import BaseModel


class EvidenceOut(BaseModel):
    type: str  # disclosure | news | theme
    text: str
    date: str | None = None
    link: str | None = None


class BeneficiaryItemOut(BaseModel):
    ticker: str
    name: str | None = None
    market: str | None = None
    track: str  # supply | theme | both
    matched_items: list[str] = []
    matched_themes: list[str] = []
    impact: str  # benefit 고정
    confidence: str
    rationale: str  # 사용자 노출 4~5문장
    caveats: str  # 사용자 노출 4~5문장 — 종목별 한계만
    evidence: list[EvidenceOut] = []
    rank: int


class BeneficiaryResponse(BaseModel):
    news_id: int
    rep_news_id: int
    status: str  # ok | no_root_companies | not_positive | no_pool | no_candidates | no_beneficiaries
    reason: str | None = None  # status != ok 일 때 어디서 왜 멈췄는지 한 문장
    event_interpretation: str | None = None
    # 이번 분석 전체의 성격 — 한 탐색 축이 비었거나 실패했을 때만 채워진다.
    # 종목별 한계가 아니므로 items[].caveats 가 아니라 여기 한 번만 실린다.
    analysis_note: str | None = None
    items: list[BeneficiaryItemOut] = []
    prompt_version: str
    disclaimer: str

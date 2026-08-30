"""beneficiary API 응답 모델 — HTTP 직렬화 계약 + 캐시 payload 형식.

캐시(news_beneficiaries.payload)는 BeneficiaryResponse.model_dump(mode="json")
전문을 저장하므로, 이 모델의 형태 변경은 PROMPT_VERSION 인상과 함께 한다.
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
    track: str  # supply | rival
    matched_items: list[str] = []
    via_themes: list[str] = []
    impact: str  # benefit 고정
    confidence: str
    rationale: str
    caveats: str | None = None
    evidence: list[EvidenceOut] = []
    rank: int


class BeneficiaryResponse(BaseModel):
    news_id: int
    rep_news_id: int
    status: str  # ok | no_candidates
    event_interpretation: str | None = None
    items: list[BeneficiaryItemOut] = []
    prompt_version: str
    disclaimer: str

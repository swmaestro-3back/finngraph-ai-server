"""인사이트 API 응답 모델.

워크플로우 내부 모델(Candidate, RankedItem, LLM 구조화 출력 등)은
graph/models.py 에 있다 — 여기는 HTTP 직렬화 계약만 남긴다.
"""

from __future__ import annotations

from pydantic import BaseModel


class EvidenceOut(BaseModel):
    type: str
    text: str
    date: str | None = None
    link: str | None = None


class InsightItemOut(BaseModel):
    ticker: str
    name: str | None = None
    impact: str
    confidence: str
    path_type: list[str]
    themes: list[str] = []
    rationale: str
    caveats: str | None = None
    evidence: list[EvidenceOut] = []
    rank: int


class InsightResponse(BaseModel):
    news_id: int
    rep_news_id: int
    status: str  # ok | no_candidates
    event_interpretation: str | None = None
    items: list[InsightItemOut] = []
    prompt_version: str
    disclaimer: str

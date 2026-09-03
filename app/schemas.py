from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class CompanyNode(BaseModel):
    model_config = ConfigDict(extra="ignore")   # 선언하지 않은 프로퍼티는 버림

    id: str = Field(description="Neo4j element_id")
    ticker: str | None = None
    name: str | None = None
    market: str | None = Field(default=None, description="KOSPI / KOSDAQ 등 상장 시장")
    country: str | None = None
    is_listed: bool | None = None
    company_id: int | None = None
    corp_code: str | None = Field(default=None, description="DART 고유번호")
    krx100: bool = False
    krx300: bool = False
    kosdaq150: bool = False


class ThemeNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Neo4j element_id")
    name: str | None = None
    description: str | None = None
    source_theme_id: int | None = None


class NewsMention(BaseModel):
    news_id: str
    item: str | None = Field(default=None, description="뉴스에서 추출된 품목/근거 문구")


class DisclosureMention(BaseModel):
    rcept_no: str = Field(description="DART 접수번호")
    item: str | None = Field(default=None, description="공시 항목명")


class SupplyRelationship(BaseModel):
    id: str = Field(description="Neo4j element_id")
    start: str = Field(description="공급하는 기업의 노드 id")
    end: str = Field(description="공급받는 기업의 노드 id")

    news_mention_count: int = Field(default=0, description="근거가 된 뉴스 건수")
    news: list[NewsMention] = Field(default_factory=list)

    disclosure_count: int = Field(default=0, description="근거가 된 공시 건수")
    disclosures: list[DisclosureMention] = Field(default_factory=list)

    first_mentioned_at: str | None = None
    last_mentioned_at: str | None = None


class BelongsToRelationship(BaseModel):
    id: str = Field(description="Neo4j element_id")
    start: str = Field(description="기업 노드 id")
    end: str = Field(description="테마 노드 id")
    reason: str | None = Field(default=None, description="해당 테마로 분류된 근거")


class SupplyChainResponse(BaseModel):
    companies: list[CompanyNode] = Field(
        default_factory=list, description="중심 기업을 포함한 경로상의 모든 기업"
    )
    relationships: list[SupplyRelationship] = Field(default_factory=list)


class ThemeResponse(BaseModel):
    theme: ThemeNode
    companies: list[CompanyNode] = Field(
        default_factory=list, description="해당 테마에 속한 기업(테마주)"
    )
    relationships: list[BelongsToRelationship] = Field(default_factory=list)

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


class EventNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Neo4j element_id")
    cluster_id: int | None = Field(default=None, description="뉴스 클러스터 id (유니크)")
    title: str | None = None
    keywords: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list, description="이벤트에 언급된 기업명")
    news_ids: list[int] = Field(default_factory=list, description="클러스터를 구성하는 뉴스 id")
    representative_news_id: int | None = None
    member_count: int | None = Field(default=None, description="클러스터에 남은 뉴스 건수")
    original_size: int | None = Field(default=None, description="정제 전 클러스터 뉴스 건수")
    first_published_at: str | None = None
    last_published_at: str | None = None
    titled_at: str | None = None
    synced_at: str | None = None


class NewsMention(BaseModel):
    news_id: str
    item: str | None = Field(default=None, description="뉴스에서 추출된 품목/근거 문구")


class DisclosureMention(BaseModel):
    rcept_no: str = Field(description="DART 접수번호")
    item: str | None = Field(default=None, description="공시 항목명")


class SupplyRelationship(BaseModel):
    """뉴스/공시 근거를 갖는 기업 간 관계. SUPPLIES_TO 외에 ACQUIRES, INVESTS_IN 도 같은 속성을 가진다."""

    id: str = Field(description="Neo4j element_id")
    type: str = Field(description="관계 타입 (SUPPLIES_TO / ACQUIRES / INVESTS_IN)")
    start: str = Field(description="관계의 시작 기업 노드 id (공급자 / 인수자 / 투자자)")
    end: str = Field(description="관계의 끝 기업 노드 id")

    news_mention_count: int = Field(default=0, description="근거가 된 뉴스 건수")
    news: list[NewsMention] = Field(default_factory=list)

    disclosure_count: int = Field(default=0, description="근거가 된 공시 건수")
    disclosures: list[DisclosureMention] = Field(default_factory=list)

    first_mentioned_at: str | None = None
    last_mentioned_at: str | None = None


class BelongsToRelationship(BaseModel):
    id: str = Field(description="Neo4j element_id")
    type: str = Field(default="BELONGS_TO", description="관계 타입")
    start: str = Field(description="기업 노드 id")
    end: str = Field(description="테마 노드 id")
    reason: str | None = Field(default=None, description="해당 테마로 분류된 근거")


class HasEventRelationship(BaseModel):
    id: str = Field(description="Neo4j element_id")
    type: str = Field(default="HAS_EVENT", description="관계 타입")
    start: str = Field(description="기업 노드 id")
    end: str = Field(description="이벤트 노드 id")


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


class CompanyEventsResponse(BaseModel):
    companies: list[CompanyNode] = Field(
        default_factory=list, description="중심 기업을 포함한 경로상의 모든 기업"
    )
    events: list[EventNode] = Field(default_factory=list, description="경로상의 모든 이벤트")
    relationships: list[HasEventRelationship] = Field(default_factory=list)


class CompanyThemesResponse(BaseModel):
    company: CompanyNode
    themes: list[ThemeNode] = Field(default_factory=list, description="해당 기업이 속한 테마")
    relationships: list[BelongsToRelationship] = Field(default_factory=list)


class CompanyResponse(BaseModel):
    companies: list[CompanyNode] = Field(
        default_factory=list, description="중심 기업과 1홉 이웃 기업"
    )
    events: list[EventNode] = Field(default_factory=list, description="기업이 언급된 이벤트")
    relationships: list[SupplyRelationship | HasEventRelationship] = Field(
        default_factory=list,
        description="중심 기업에 붙은 간선 중 BELONGS_TO 를 제외한 전부. type 으로 구분한다.",
    )


class NewsGraphResponse(BaseModel):
    """뉴스 한 건을 근거로 추출된 기업 간 관계(시드)와 hop 확장 결과. 테마·이벤트는 담지 않는다."""

    companies: list[CompanyNode] = Field(
        default_factory=list, description="시드 관계의 양끝 기업과 확장으로 붙은 기업"
    )
    relationships: list[SupplyRelationship] = Field(default_factory=list)
    seed_relationship_ids: list[str] = Field(
        default_factory=list, description="이 뉴스를 근거로 가진 관계 id — 나머지는 홉 확장으로 딸려온 것"
    )
    seed_company_ids: list[str] = Field(
        default_factory=list, description="시드 관계의 양끝 기업 id — 기사에 등장한 기업"
    )
    truncated: bool = Field(
        default=False, description="전체 노드 상한에 걸려 확장 이웃을 일부 버렸는가"
    )

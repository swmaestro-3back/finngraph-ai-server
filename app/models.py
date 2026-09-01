from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    COMPANY = "Company"
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"

    THEME = "Theme"

    COUNTRY = "Country"
    COMMODITY = "Commodity"
    PRODUCT = "Product"


class RelationshipType(StrEnum):
    # 기본 관계
    SUPPLIES_TO = "SUPPLIES_TO"
    EXPORTS_TO = "EXPORTS_TO"
    ACQUIRES = "ACQUIRES"
    DIVESTS_FROM = "DIVESTS_FROM"
    INVESTS_IN = "INVESTS_IN"
    PARTNERS_WITH = "PARTNERS_WITH"
    LOCATED_IN = "LOCATED_IN"
    PRODUCES = "PRODUCES"
    COMPETES_WITH = "COMPETES_WITH"
    DEVELOPS = "DEVELOPS"
    SANCTIONS = "SANCTIONS"

    # item 기반 분해 관계
    SUPPLIES = "SUPPLIES"
    SUPPLIED_TO = "SUPPLIED_TO"
    EXPORTS = "EXPORTS"
    EXPORTED_TO = "EXPORTED_TO"

    # 테마 주식 관계
    BELONGS_TO = "BELONGS_TO"

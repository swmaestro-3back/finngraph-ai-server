from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class MarketIndex(StrEnum):
    KRX100 = "krx100"
    KRX300 = "krx300"
    KOSDAQ150 = "kosdaq150"

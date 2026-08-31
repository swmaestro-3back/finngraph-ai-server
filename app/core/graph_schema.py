"""Neo4j 그래프 스키마 어휘 — 라벨·관계 타입·시장 구분.

두 기능(knowledge_graph 조회, beneficiary 에이전트)이 같은 그래프를 읽으므로
라벨 어휘는 어느 한 기능의 소유가 아니라 공유 인프라다 — 그래서 둘 다 이미
의존하는 core 에 둔다(기능 패키지끼리는 서로를 모른다).

Cypher 에는 f-string 보간으로 들어간다 — StrEnum 이라 그대로 문자열이 되고,
enum 상수라 주입 위험이 없다(사용자 입력은 전부 파라미터로 나간다).
"""

from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    COMPANY = "Company"
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"

    THEME = "Theme"


class RelationshipType(StrEnum):
    # 기본 관계
    SUPPLIES_TO = "SUPPLIES_TO"
    ACQUIRES = "ACQUIRES"
    INVESTS_IN = "INVESTS_IN"

    # 테마 주식 관계
    BELONGS_TO = "BELONGS_TO"


# 추천·조회 대상 시장 — 그 외(KONEX 등)는 제외. 그래프에서 시장은 노드 라벨이자
# market 속성값이라 같은 이름을 두 방식으로 쓴다: 라벨은 NodeLabel.KOSPI,
# 속성 푸시다운(`n.market IN $markets`)과 시장별 쿼터 로직은 이 튜플을 쓴다.
MARKETS: tuple[str, ...] = (NodeLabel.KOSPI.value, NodeLabel.KOSDAQ.value)

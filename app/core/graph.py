"""Neo4j 그래프 어휘 — 라벨·관계 타입.

Cypher 에는 f-string 보간으로 들어간다 — StrEnum 이라 그대로 문자열이 되고,
enum 상수라 주입 위험이 없다(사용자 입력은 전부 파라미터로 나간다).
"""

from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    COMPANY = "Company"
    THEME = "Theme"
    EVENT = "Event"


class RelationshipType(StrEnum):
    SUPPLIES_TO = "SUPPLIES_TO"  # (:Company)-[:SUPPLIES_TO]->(:Company)
    BELONGS_TO = "BELONGS_TO"  # (:Company)-[:BELONGS_TO]->(:Theme)
    HAS_EVENT = "HAS_EVENT"  # (:Company)-[:HAS_EVENT]->(:Event)
    ACQUIRES = "ACQUIRES"  # (:Company)-[:ACQUIRES]->(:Company), SUPPLIES_TO 와 같은 근거 속성
    INVESTS_IN = "INVESTS_IN"  # (:Company)-[:INVESTS_IN]->(:Company), SUPPLIES_TO 와 같은 근거 속성

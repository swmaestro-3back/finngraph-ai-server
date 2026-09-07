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

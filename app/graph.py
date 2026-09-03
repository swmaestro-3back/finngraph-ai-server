from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    COMPANY = "Company"
    THEME = "Theme"


class RelationshipType(StrEnum):
    SUPPLIES_TO = "SUPPLIES_TO"  # (:Company)-[:SUPPLIES_TO]->(:Company)
    BELONGS_TO = "BELONGS_TO"  # (:Company)-[:BELONGS_TO]->(:Theme)

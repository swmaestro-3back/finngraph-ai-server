from __future__ import annotations

from pydantic import BaseModel
from typing import TypedDict, Literal

from graph.models import Anchor, Candidate, NewsContext, RankedItem


class ExpansionPlan(BaseModel) :
    event_summary: str
    polarity: Literal["positive", "negative"]
    core_items: list[str]

class GraphState(TypedDict, total=False):
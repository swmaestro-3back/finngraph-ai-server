"""beneficiary 프롬프트 명세.

PROMPT_VERSION 은 응답 메타데이터이자 캐시 키다 — 프롬프트·패킹 형식·규칙·
LLM 스택을 바꾸면 반드시 올린다(b2, b3, ...). v1(app/graph)의 v15 계열과
독립된 b 계열을 쓴다.
"""

from beneficiary.prompts.beneficiary_judge import BENEFICIARY_JUDGE_SYSTEM
from beneficiary.prompts.news_plan import NEWS_PLAN_SYSTEM
from beneficiary.prompts.rival_filter import RIVAL_FILTER_SYSTEM
from beneficiary.prompts.supply_filter import SUPPLY_FILTER_SYSTEM

PROMPT_VERSION = "b1"

DISCLAIMER = (
    "본 분석은 수집된 공시·뉴스·재무 데이터에 기반한 정보 제공 목적이며, "
    "투자 자문이 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다."
)

__all__ = [
    "BENEFICIARY_JUDGE_SYSTEM",
    "DISCLAIMER",
    "NEWS_PLAN_SYSTEM",
    "PROMPT_VERSION",
    "RIVAL_FILTER_SYSTEM",
    "SUPPLY_FILTER_SYSTEM",
]

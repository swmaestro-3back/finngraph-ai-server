"""beneficiary 프롬프트 명세.

PROMPT_VERSION 은 응답·트레이스에 실리는 메타데이터다 — 프롬프트·패킹 형식·
규칙·LLM 스택을 바꾸면 반드시 올려서(b1, b2, ...) 소비자가 형식 변화를
감지할 수 있게 한다.
"""

from beneficiary.agent.prompts.evaluator import EVALUATOR_SYSTEM
from beneficiary.agent.prompts.news_plan import NEWS_PLAN_SYSTEM
from beneficiary.agent.prompts.supply_filter import SUPPLY_FILTER_SYSTEM
from beneficiary.agent.prompts.theme_filter import THEME_FILTER_SYSTEM

PROMPT_VERSION = "c1"

DISCLAIMER = (
    "본 분석은 수집된 공시·뉴스·재무 데이터에 기반한 정보 제공 목적이며, "
    "투자 자문이 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다."
)

__all__ = [
    "EVALUATOR_SYSTEM",
    "DISCLAIMER",
    "NEWS_PLAN_SYSTEM",
    "PROMPT_VERSION",
    "SUPPLY_FILTER_SYSTEM",
    "THEME_FILTER_SYSTEM",
]

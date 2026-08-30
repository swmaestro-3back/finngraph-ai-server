"""beneficiary 프롬프트 명세.

PROMPT_VERSION 은 응답 메타데이터다 — 프롬프트·패킹 형식·규칙·LLM 스택을
바꾸면 반드시 올린다(b2, b3, ...). v1 의 v15 계열과 독립된 b 계열을 쓴다.
(응답 캐시는 2026-08-30 제거 — 버전은 이제 트레이스·응답 식별용이다.)
이력: b1 → b2 (2026-08-30): 용어 개명 Anchor→RootCompany — 프롬프트·패킹
라벨의 '앵커'를 '루트 기업'으로 교체.
"""

from graph.prompts.beneficiary_judge import BENEFICIARY_JUDGE_SYSTEM
from graph.prompts.news_plan import NEWS_PLAN_SYSTEM
from graph.prompts.rival_filter import RIVAL_FILTER_SYSTEM
from graph.prompts.supply_filter import SUPPLY_FILTER_SYSTEM

PROMPT_VERSION = "b2"

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

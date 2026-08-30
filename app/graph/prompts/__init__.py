"""프롬프트 명세.

PROMPT_VERSION 은 응답 메타데이터다 — 프롬프트·규칙·후보 구성·LLM 스택을
바꾸면 올려서 LangSmith 트레이스·응답을 버전으로 구분할 수 있게 한다.

이력: ~v13 두-에이전트(공급망∥역발상) 구조 → v14 supply_chain 단일 에이전트
(SUPPLIES_TO 1-hop → 공시 수 상위 3개 → 재무 테이블 table RAG 로 5단계
체크리스트 랭킹)로 전환, ripple 분기·테마 벡터 검색 제거 → v15 1-hop 탐색을
Neo4j 로 이전 (object company 를 ticker 로 특정, subject ticker 기업 제외,
disclosure_count 간선 속성 기준 상위 3개).
"""

from graph.prompts.supply_judge import SUPPLY_JUDGE_SYSTEM

PROMPT_VERSION = "v15"

DISCLAIMER = (
    "본 분석은 수집된 공시·뉴스·재무 데이터에 기반한 정보 제공 목적이며, "
    "투자 자문이 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다."
)

__all__ = [
    "DISCLAIMER",
    "PROMPT_VERSION",
    "SUPPLY_JUDGE_SYSTEM",
]

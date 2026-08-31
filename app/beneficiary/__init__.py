"""공급망 수혜주(beneficiary) 에이전트 — 뉴스 사건 → 수혜 종목 추천 피처.

설계: docs/superpowers/specs/2026-08-30-beneficiary-agent-design.md (로컬 전용).

패키지 경계 (바깥 → 안 순서, 역방향 의존 금지):
    api/routes/news.py → service → agent/ → repository → core

- schemas.py    : HTTP 응답 계약 (이 피처의 엔드포인트 전용)
- service.py    : 유스케이스 — HTTP 계약을 아는 유일한 곳
- repository.py : PG·Neo4j 조회
- models.py     : 도메인 전달 모델 + LLM 구조화 출력 계약
- agent/        : LangGraph 본체 — FastAPI 를 모른다(agent/ 참조)
"""

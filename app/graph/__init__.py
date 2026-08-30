"""공급망 수혜주(beneficiary) 에이전트 (극성 2트랙).

설계: docs/superpowers/specs/2026-08-30-beneficiary-agent-design.md (로컬 전용).
v1 이슈 인사이트 에이전트(구 app/graph·app/insights)는 삭제됐다 — v1 의 읽기
쿼리 5개는 graph/repository.py 로 이관돼 이 패키지가 소유한다. 트랙별
expand/filter 노드는 graph/subgraph/{supply_chain,theme}/ 서브그래프 소관이고,
최상위 노드(analyze/select/enrich/judge)는 graph/nodes/ 에 있다.
"""

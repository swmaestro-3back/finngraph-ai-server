"""지식그래프 조회 피처 — 기업·테마 subgraph 와 관계 상세.

- repository.py : Neo4j READ 쿼리
- schemas.py    : GraphResponse 등 응답 스키마 + Record 직렬화

라벨·관계 타입 enum(NodeLabel/RelationshipType)은 beneficiary 와 공유하므로
core/graph_schema.py 가 소유한다.
"""

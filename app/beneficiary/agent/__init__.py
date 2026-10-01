"""LangGraph 에이전트 본체 — 호재 전용 병렬 2트랙(공급망 / 시나리오 테마).

이 하위 패키지는 전송 계층을 모른다 — fastapi·beneficiary.schemas 를 import
하지 않는다. HTTP 밖(배치·스케줄러·LangGraph Studio)에서도 그대로 돌리기
위해서다. 밖으로 나가는 의존은 beneficiary.models / beneficiary.repository /
core 까지다.

- workflow.py : 부모 그래프 조립·라우팅 + 트랙 래퍼. 정지 규칙은 error/status
                둘뿐이다. 노드 정책(재시도·타임아웃·예외 강등)은 트랙 안쪽
                노드에 붙는다 — 래퍼에는 붙이지 않는다.
- state.py    : 노드 간 공유 상태
- subgraphs/  : 트랙별 서브그래프 — supply(그래프 간선) / theme(벡터 검색).
                각각 graph.py(조립·노드 정책) / nodes.py(expand·filter) /
                state.py 를 갖고, 팬인에는 결과 객체를 값으로 올린다.
- nodes/      : 트랙 공통 단계 노드 (planner · candidate_selector ·
                finance_collector · evaluator)
- prompts/    : LLM 시스템 프롬프트 + PROMPT_VERSION
- utils/      : Bedrock LCEL 체인·임베딩·프롬프트 패킹·LLM 출력 후처리
"""

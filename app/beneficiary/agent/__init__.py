"""LangGraph 에이전트 본체 — 극성 2트랙(공급망/경쟁사) 단일 그래프.

이 하위 패키지는 전송 계층을 모른다 — fastapi·beneficiary.schemas 를 import
하지 않는다. HTTP 밖(배치·스케줄러·LangGraph Studio)에서도 그대로 돌리기
위해서다. 밖으로 나가는 의존은 beneficiary.models / beneficiary.repository /
core 까지다.

- workflow.py : 그래프 조립·라우팅 + 노드 정책(재시도·타임아웃·예외 강등).
                정지 규칙은 error/status 둘뿐이다.
- state.py    : 노드 간 공유 상태
- nodes/      : 각 단계 노드 (트랙별 expand/filter 포함)
- prompts/    : LLM 시스템 프롬프트 + PROMPT_VERSION
- utils/      : Bedrock LCEL 체인·프롬프트 패킹·LLM 출력 후처리
"""

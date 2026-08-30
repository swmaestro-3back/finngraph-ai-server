"""Bedrock 호출 계층 — langchain-aws 기반.

- 심사는 ChatBedrockConverse + with_structured_output(pydantic) 으로 tool 강제
  구조화 출력을 받고, with_retry 로 일시 오류를 1회 재시도한다 (노드는 최종
  실패만 잡아 error 로 강등한다).
- 노드는 이 모듈을 `from graph.utils import llm` 으로 들고 다닌다 — 테스트가
  모듈 속성을 monkeypatch 하는 시임(seam)이다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from botocore.config import Config
from langchain_core.messages import HumanMessage, SystemMessage

from core.config import settings
from graph.models import JudgeOutput
from graph.prompts import SUPPLY_JUDGE_SYSTEM

MAX_OUTPUT_TOKENS = 8192
LLM_ATTEMPTS = 2  # with_retry 총 시도 횟수


def _inject_bearer_token() -> None:
    # boto3 가 env 의 bearer 토큰을 읽으므로 클라이언트 생성 전에 주입한다.
    if settings.aws_bearer_token_bedrock:
        os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", settings.aws_bearer_token_bedrock)


def _botocore_config() -> Config:
    return Config(read_timeout=120, connect_timeout=30, retries={"max_attempts": 2, "mode": "standard"})


@lru_cache
def _judge_runnable():
    from langchain_aws import ChatBedrockConverse

    _inject_bearer_token()
    chat = ChatBedrockConverse(
        model=settings.bedrock_judge_model,
        region_name=settings.bedrock_region or None,
        temperature=0.1,
        max_tokens=MAX_OUTPUT_TOKENS,
        config=_botocore_config(),
    )
    return chat.with_structured_output(JudgeOutput).with_retry(stop_after_attempt=LLM_ATTEMPTS)


async def judge_supply(prompt: str) -> JudgeOutput:
    return await _judge_runnable().ainvoke(
        [SystemMessage(SUPPLY_JUDGE_SYSTEM), HumanMessage(prompt)]
    )

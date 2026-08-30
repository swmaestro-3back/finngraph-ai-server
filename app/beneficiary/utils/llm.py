"""beneficiary Bedrock 호출 계층 — v1(graph/utils/llm.py) 패턴 복사.

- 4개 러너블(lru_cache) / 실행당 호출은 3회: plan → filter(supply 또는
  rivals) → judge.
- ChatBedrockConverse + with_structured_output(pydantic) + with_retry.
- 노드는 이 모듈을 `from beneficiary.utils import llm` 으로 들고 다닌다 —
  테스트가 모듈 속성을 monkeypatch 하는 시임(seam)이다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from botocore.config import Config
from langchain_core.messages import HumanMessage, SystemMessage

from beneficiary.models import FilterOutput, JudgeOutput, NewsPlan
from beneficiary.prompts import (
    BENEFICIARY_JUDGE_SYSTEM,
    NEWS_PLAN_SYSTEM,
    RIVAL_FILTER_SYSTEM,
    SUPPLY_FILTER_SYSTEM,
)
from core.config import settings

MAX_OUTPUT_TOKENS_LIGHT = 4096
MAX_OUTPUT_TOKENS_JUDGE = 8192
LLM_ATTEMPTS = 2  # with_retry 총 시도 횟수


def _inject_bearer_token() -> None:
    # boto3 가 env 의 bearer 토큰을 읽으므로 클라이언트 생성 전에 주입한다.
    if settings.aws_bearer_token_bedrock:
        os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", settings.aws_bearer_token_bedrock)


def _botocore_config() -> Config:
    return Config(read_timeout=120, connect_timeout=30, retries={"max_attempts": 2, "mode": "standard"})


def _light_chat(temperature: float):
    from langchain_aws import ChatBedrockConverse

    _inject_bearer_token()
    return ChatBedrockConverse(
        model=settings.bedrock_light_model,
        region_name=settings.bedrock_region or None,
        temperature=temperature,
        max_tokens=MAX_OUTPUT_TOKENS_LIGHT,
        config=_botocore_config(),
    )


@lru_cache
def _plan_runnable():
    return _light_chat(0.1).with_structured_output(NewsPlan).with_retry(stop_after_attempt=LLM_ATTEMPTS)


@lru_cache
def _supply_filter_runnable():
    return _light_chat(0.0).with_structured_output(FilterOutput).with_retry(stop_after_attempt=LLM_ATTEMPTS)


@lru_cache
def _rival_filter_runnable():
    return _light_chat(0.0).with_structured_output(FilterOutput).with_retry(stop_after_attempt=LLM_ATTEMPTS)


@lru_cache
def _judge_runnable():
    from langchain_aws import ChatBedrockConverse

    _inject_bearer_token()
    chat = ChatBedrockConverse(
        model=settings.bedrock_judge_model,
        region_name=settings.bedrock_region or None,
        temperature=0.1,
        max_tokens=MAX_OUTPUT_TOKENS_JUDGE,
        config=_botocore_config(),
    )
    return chat.with_structured_output(JudgeOutput).with_retry(stop_after_attempt=LLM_ATTEMPTS)


async def plan_news(prompt: str) -> NewsPlan:
    return await _plan_runnable().ainvoke([SystemMessage(NEWS_PLAN_SYSTEM), HumanMessage(prompt)])


async def filter_supply(prompt: str) -> FilterOutput:
    return await _supply_filter_runnable().ainvoke(
        [SystemMessage(SUPPLY_FILTER_SYSTEM), HumanMessage(prompt)]
    )


async def filter_rivals(prompt: str) -> FilterOutput:
    return await _rival_filter_runnable().ainvoke(
        [SystemMessage(RIVAL_FILTER_SYSTEM), HumanMessage(prompt)]
    )


async def judge_beneficiary(prompt: str) -> JudgeOutput:
    return await _judge_runnable().ainvoke(
        [SystemMessage(BENEFICIARY_JUDGE_SYSTEM), HumanMessage(prompt)]
    )

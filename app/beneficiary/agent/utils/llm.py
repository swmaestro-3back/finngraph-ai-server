"""beneficiary Bedrock 호출 계층 — LCEL 체인 3개.

- 체인 형태: ChatPromptTemplate | Chat.with_structured_output(pydantic).with_retry()
- 실행당 LLM 호출은 3회: plan → filter_supply → evaluate.
  체인 조립은 lru_cache 로 프로세스당 1회다.
- 노드는 이 모듈을 `from beneficiary.agent.utils import llm` 으로 들고 다닌다 —
  테스트가 모듈 속성을 monkeypatch 하는 시임(seam)이다. 그래서 체인을 그대로
  노출하지 않고, packer 가 렌더한 프롬프트 문자열을 받는 얇은 async 래퍼를
  유지한다.
- run_name 은 LangSmith 트레이스에서 이 호출을 식별하는 이름이다 — 노드 이름과
  맞춰 둬야 트레이스에서 어느 단계인지 바로 읽힌다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from botocore.config import Config
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from beneficiary.models import EvaluatorOutput, FilterOutput, NewsPlan
from beneficiary.agent.prompts import (
    EVALUATOR_SYSTEM,
    NEWS_PLAN_SYSTEM,
    SUPPLY_FILTER_SYSTEM,
    THEME_FILTER_SYSTEM,
)
from core.config import settings

MAX_OUTPUT_TOKENS_LIGHT = 4096
MAX_OUTPUT_TOKENS_EVALUATOR = 8192
LLM_ATTEMPTS = 2  # with_retry 총 시도 횟수


def _inject_bearer_token() -> None:
    # boto3 가 env 의 bearer 토큰을 읽으므로 클라이언트 생성 전에 주입한다.
    if settings.aws_bearer_token_bedrock:
        os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", settings.aws_bearer_token_bedrock)


def _botocore_config() -> Config:
    return Config(read_timeout=120, connect_timeout=30, retries={"max_attempts": 2, "mode": "standard"})


def _chat(model: str, temperature: float, max_tokens: int):
    from langchain_aws import ChatBedrockConverse

    _inject_bearer_token()
    return ChatBedrockConverse(
        model=model,
        region_name=settings.bedrock_region or None,
        temperature=temperature,
        max_tokens=max_tokens,
        config=_botocore_config(),
    )


def _chain(system: str, schema, chat, run_name: str) -> Runnable:
    """system 프롬프트 + {context} → 구조화 출력 체인.

    프롬프트에 리터럴 중괄호가 없어 기본 f-string 포맷을 쓴다 — 프롬프트에
    중괄호를 넣게 되면 template_format="mustache" 로 바꿔야 한다. context 로
    주입되는 packer 출력은 값이라 재파싱되지 않으므로 그쪽은 안전하다.

    with_retry 는 모델 쪽에만 건다 — 프롬프트 포맷은 결정적이라 재시도할
    이유가 없고, 재시도 범위를 기존(구조화 출력 파싱 포함)과 같게 유지한다.
    """

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", "{context}")])
    structured = chat.with_structured_output(schema).with_retry(stop_after_attempt=LLM_ATTEMPTS)
    return (prompt | structured).with_config(run_name=run_name)


@lru_cache
def _light_chat(temperature: float):
    """계획·선별 공용 경량 모델 — temperature 별로 1개."""
    return _chat(settings.bedrock_light_model, temperature, MAX_OUTPUT_TOKENS_LIGHT)


@lru_cache
def _plan_chain() -> Runnable:
    return _chain(NEWS_PLAN_SYSTEM, NewsPlan, _light_chat(0.1), "plan_news")


@lru_cache
def _supply_filter_chain() -> Runnable:
    return _chain(SUPPLY_FILTER_SYSTEM, FilterOutput, _light_chat(0.0), "filter_supply")


@lru_cache
def _theme_filter_chain() -> Runnable:
    return _chain(THEME_FILTER_SYSTEM, FilterOutput, _light_chat(0.0), "filter_theme")


@lru_cache
def _evaluator_chain() -> Runnable:
    chat = _chat(settings.bedrock_evaluator_model, 0.1, MAX_OUTPUT_TOKENS_EVALUATOR)
    return _chain(EVALUATOR_SYSTEM, EvaluatorOutput, chat, "evaluate_beneficiary")


async def plan_news(prompt: str) -> NewsPlan:
    return await _plan_chain().ainvoke({"context": prompt})


async def filter_supply(prompt: str) -> FilterOutput:
    return await _supply_filter_chain().ainvoke({"context": prompt})


async def filter_theme(prompt: str) -> FilterOutput:
    return await _theme_filter_chain().ainvoke({"context": prompt})


async def evaluate_beneficiary(prompt: str) -> EvaluatorOutput:
    return await _evaluator_chain().ainvoke({"context": prompt})

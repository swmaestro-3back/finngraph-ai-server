"""Bedrock 임베딩 호출 계층 — theme 트랙의 시나리오 질의 벡터화.

llm.py 와 같은 규약을 쓴다: lru_cache 로 클라이언트를 프로세스당 1회 조립하고,
노드는 이 모듈을 속성으로 들고 다닌다(테스트가 monkeypatch 하는 시임).

모델·차원·normalize 는 finngraph-etl 이 reason_embedding 을 만들 때 쓴 것과
반드시 같아야 한다(amazon.titan-embed-text-v2:0 / 1024 / True) — 하나라도
다르면 벡터 공간이 달라 유사도가 무의미해진다. 그래서 래퍼 라이브러리를 거치지
않고 ETL 과 같은 요청 body 를 직접 보낸다.
"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache

from botocore.config import Config

from core.config import settings

EMBED_DIMENSIONS = 1024  # 인덱스 vector.dimensions 와 일치해야 한다


@lru_cache
def _client():
    import boto3

    from beneficiary.agent.utils.llm import _inject_bearer_token

    _inject_bearer_token()
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region or None,
        config=Config(read_timeout=30, connect_timeout=10,
                      retries={"max_attempts": 2, "mode": "standard"}),
    )


def _embed_one(text: str) -> list[float]:
    response = _client().invoke_model(
        modelId=settings.bedrock_embedding_model,
        body=json.dumps({"inputText": text,
                         "dimensions": EMBED_DIMENSIONS,
                         "normalize": True}),
    )
    return json.loads(response["body"].read())["embedding"]


async def embed_queries(queries: list[str]) -> list[list[float]]:
    """probe 질의들을 동시에 벡터화한다 — 순서는 입력 순서와 같다.

    Titan invoke_model 은 요청당 텍스트 1건이라 배치 API 가 없다. probe 는 최대
    4개이므로 스레드로 동시에 던진다.
    """

    if not queries:
        return []
    return list(await asyncio.gather(
        *(asyncio.to_thread(_embed_one, query) for query in queries)
    ))

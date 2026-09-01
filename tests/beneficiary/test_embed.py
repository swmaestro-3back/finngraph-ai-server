"""임베딩 유틸 — 배치 1회 호출과 시임(seam) 보장."""

from __future__ import annotations

import pytest

from beneficiary.agent.utils import embed


@pytest.mark.asyncio
async def test_embed_queries_preserves_input_order(monkeypatch):
    """동시 호출이라도 반환 순서는 입력 순서여야 한다 — probe 와 zip 되기 때문."""
    monkeypatch.setattr(embed, "_embed_one", lambda text: [float(len(text))])

    vectors = await embed.embed_queries(["변압기", "액침냉각시스템"])

    assert vectors == [[3.0], [7.0]]


@pytest.mark.asyncio
async def test_embed_queries_sends_etl_request_shape(monkeypatch):
    """ETL 과 같은 body 여야 벡터 공간이 일치한다 — dimensions/normalize 필수."""
    import json as _json

    sent = {}

    class _FakeClient:
        def invoke_model(self, modelId, body):
            sent["modelId"] = modelId
            sent["body"] = _json.loads(body)

            class _Body:
                def read(self_inner):
                    return _json.dumps({"embedding": [0.1] * 4})

            return {"body": _Body()}

    monkeypatch.setattr(embed, "_client", lambda: _FakeClient())

    await embed.embed_queries(["변압기"])

    assert sent["modelId"] == "amazon.titan-embed-text-v2:0"
    assert sent["body"] == {"inputText": "변압기", "dimensions": 1024, "normalize": True}


@pytest.mark.asyncio
async def test_embed_queries_returns_empty_without_calling(monkeypatch):
    def _boom():
        raise AssertionError("빈 입력에 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(embed, "_client", _boom)
    assert await embed.embed_queries([]) == []

# finngraph-kg-api

REST API Server for financial knowledge graph which is created by triplet extraction pipeline in `finngraph-etl` repository.

Supports only `GET` methods - used exclusively in the knowledge graph explorer.

## Project Overview

Finngraph KG API exposes a **financial knowledge graph** stored in Neo4j over a REST API.

The graph connects companies (KOSPI / KOSDAQ) and themes through relationships like supply
chains, acquisitions, and investments.

Each read endpoint returns a **subgraph** (nodes + relationships) centered on the requested
entity, which a client can render as an interactive graph. Edge details (full provenance such as
source news and sentences) are fetched lazily per relationship.

**API endpoints** (all prefixed with `/api/v1`):

| Method & Path | Description |
| --- | --- |
| `GET /companies/{ticker}` | Subgraph within 3 hops of the given company |
| `GET /themes/{name}` | Subgraph centered on a theme |
| `GET /relationships/{element_id}` | Full detail (provenance) of a single relationship |
| `GET /news/{news_id}/beneficiaries` | 호재 뉴스의 수혜 종목을 병렬 2트랙(공급망 / 시나리오 테마)으로 추천. 악재는 not_positive 로 정상 종료. 매 호출 ~20초 동기 생성 (캐시 없음) |

수혜주 응답은 종목 목록(`items`) 외에 사용자에게 그대로 보여줄 문장을 함께 싣는다 —
`event_interpretation`(분석 서두), 종목별 `rationale`·`caveats`, 그리고 한 탐색 축이
비었거나 실패했을 때만 채워지는 `analysis_note`(이번 분석 전체의 성격). `status` 가
`ok` 가 아니면 `reason` 이 어디서 왜 멈췄는지 한 문장으로 알려준다.

## Directory Structure

기능(feature) 단위 패키지를 쓴다 — 한 기능의 스키마·서비스·데이터 접근이
한 폴더에 모여 있고, `app/api/routes/` 는 그 기능을 HTTP 로 노출하는 얇은
어댑터다. 의존 방향은 `api → service → agent → repository → core` 한 방향뿐이다.

```
finngraph-kg-api/
├── app/
│   ├── main.py                   # FastAPI app entrypoint (lifespan, router mounting)
│   ├── api/
│   │   ├── main.py               # Aggregates all route routers into api_router
│   │   └── routes/               # Endpoint handlers (얇게 — 로직은 각 기능 패키지에)
│   │       ├── company.py
│   │       ├── theme.py
│   │       ├── relationship.py
│   │       └── news.py
│   ├── knowledge_graph/          # 지식그래프 조회 기능
│   │   ├── repository.py         # Neo4j READ queries (subgraph / relationship lookups)
│   │   └── schemas.py            # Pydantic response schemas (GraphResponse, ...)
│   ├── beneficiary/              # 수혜주 추천 에이전트 기능
│   │   ├── schemas.py            # HTTP 응답 계약
│   │   ├── service.py            # 유스케이스 — HTTP 계약을 아는 유일한 곳
│   │   ├── repository.py         # Postgres·Neo4j 조회
│   │   ├── models.py             # 도메인 모델 + LLM 구조화 출력 계약
│   │   └── agent/                # LangGraph 본체 — FastAPI 를 모른다
│   │       ├── workflow.py       # 그래프 조립·라우팅 (팬아웃/팬인)
│   │       ├── state.py
│   │       ├── nodes/            # 공통 단계 노드 (planner/candidate_selector/finance_collector/evaluator)
│   │       ├── subgraphs/        # 병렬 트랙 서브그래프 (supply/, theme/ — 각자 nodes·state·graph)
│   │       ├── prompts/          # 시스템 프롬프트 + PROMPT_VERSION
│   │       └── utils/            # Bedrock 러너블·프롬프트 패킹·출력 후처리
│   ├── core/
│   │   ├── config.py             # Settings loaded from .env (pydantic-settings)
│   │   ├── graph_schema.py       # 그래프 어휘 (NodeLabel, RelationshipType, MARKETS) — 두 기능 공유
│   │   ├── neo4j.py              # Neo4jClient — async driver 싱글톤
│   │   ├── postgres.py           # PostgresClient — async 커넥션 풀 싱글톤
│   │   └── logger.py             # Logging setup
├── tests/
│   └── beneficiary/              # 단위 테스트 + 통합 테스트(`integration` 마커, 로컬 DB 필요)
├── Dockerfile                    # API image build
├── docker-compose.yml            # api service (Neo4j·Postgres 는 finngraph-etl 스택 공유)
├── pyproject.toml                # Project metadata & dependencies (uv)
└── .env.example                  # Environment variable template
```

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `NEO4J_URI` | Bolt connection URI (use `bolt://localhost:7687` for local runs) |
| `NEO4J_USERNAME` | Neo4j username |
| `NEO4J_PASSWORD` | Neo4j password |
| `NEO4J_DATABASE` | Database name to use |
| `NEO4J_REASON_VECTOR_INDEX` | `BELONGS_TO.reason_embedding` 관계 벡터 인덱스 이름 (기본 `belongs_to_reason_embedding`). 시나리오 테마 트랙이 이 인덱스로 검색한다 |
| `DATABASE_URL` | finngraph-etl 의 ETL Postgres 접속 URL (수혜주 기능이 원장·재무를 직접 읽음) |
| `BEDROCK_REGION` | Bedrock 리전 (기본 `us-east-1`) |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock API 키 (ETL 레포와 동일 발급분 사용 가능) |
| `BEDROCK_EVALUATOR_MODEL` | 후보 심사 모델 (기본 `us.anthropic.claude-sonnet-4-6`) |
| `BEDROCK_LIGHT_MODEL` | 계획·선별용 경량 모델 (기본 `us.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| `BEDROCK_EMBEDDING_MODEL` | 시나리오 테마 검색용 임베딩 모델 (기본 `amazon.titan-embed-text-v2:0`). **finngraph-etl 이 `reason_embedding` 을 만들 때 쓴 모델과 반드시 같아야 한다** — 다르면 벡터가 비교 불가능한데 오류 없이 엉뚱한 결과가 나온다 |
| `LANGSMITH_TRACING` | LLM·워크플로우 트레이싱 on/off (기본 `false`) |
| `LANGSMITH_API_KEY` | LangSmith API 키 (`LANGSMITH_TRACING=true` 일 때만 필요) |
| `LANGSMITH_PROJECT` | 트레이스가 쌓일 프로젝트 이름 (기본 `finngraph`) |
| `LANGSMITH_ENDPOINT` | LangSmith 엔드포인트 (기본 `https://api.smith.langchain.com`) |

> When running with Docker, `NEO4J_URI` and `DATABASE_URL` are automatically overridden inside the container to the finngraph-etl network service names (`bolt://neo4j:7687`, `db:5432`), so you can leave the `.env` values as the local ones.

## How to Run

Requires Python 3.14+, [uv](https://docs.astral.sh/uv/), and Docker.

### 1. Install dependencies

```bash
uv sync
```

### 2. Run with Docker

Neo4j and Postgres are **not** started here — the API shares the instances from the
[finngraph-etl](../finngraph-etl) stack (same data the ETL pipelines load). Start those first:

```bash
cd ../finngraph-etl && docker compose up -d db neo4j neo4j-init
```

Then build and start the API server (it joins the `finngraph-etl_default` network):

```bash
docker compose up -d --build
```

- API: http://localhost:8000
- **Swagger UI: http://localhost:8000/docs**
- ReDoc: http://localhost:8000/redoc
- Neo4j Browser: http://localhost:7474 (finngraph-etl 스택이 노출)

The image is not rebuilt automatically after you change the source, so always pass `--build`.

```bash
# check status
docker compose ps

# tail api logs
docker compose logs -f api

# stop (Neo4j·Postgres 는 finngraph-etl 소관이라 여기서 내려가지 않는다)
docker compose down
```

## Testing

단위 테스트만 — DB 없이 어디서나 돈다.

```bash
uv run pytest -m "not integration"
```

통합 테스트까지 포함하려면 finngraph-etl 의 Postgres·Neo4j 가 떠 있어야 한다
(`integration` 마커가 붙은 `test_repository_integration.py`·`test_service_integration.py`
가 실제 DB 에 시드를 심고 지운다). 마커를 걸지 않은 `uv run pytest` 는 이 둘까지
같이 돌리므로, DB 가 없으면 실패한다.

```bash
cd ../finngraph-etl && docker compose up -d db neo4j neo4j-init
cd - && uv run pytest
```
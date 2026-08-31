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
| `GET /news/{news_id}/beneficiaries` | 뉴스 사건의 수혜 종목을 극성 2트랙(공급망/경쟁사)으로 추천. 매 호출 ~20초 동기 생성 (캐시 없음) |

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
│   │       ├── workflow.py       # 그래프 조립·라우팅
│   │       ├── state.py
│   │       ├── nodes/            # 각 단계 노드 (트랙별 expand/filter 포함)
│   │       ├── prompts/          # 시스템 프롬프트 + PROMPT_VERSION
│   │       └── utils/            # Bedrock 러너블·프롬프트 패킹·출력 후처리
│   ├── core/
│   │   ├── config.py             # Settings loaded from .env (pydantic-settings)
│   │   ├── graph_schema.py       # 그래프 어휘 (NodeLabel, RelationshipType, MARKETS) — 두 기능 공유
│   │   ├── neo4j.py              # Neo4jClient — async driver 싱글톤
│   │   ├── postgres.py           # PostgresClient — async 커넥션 풀 싱글톤
│   │   └── logger.py             # Logging setup
├── tests/
│   └── beneficiary/              # 단위 테스트 + 통합 테스트(`-m integration`, 로컬 DB 필요)
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
| `DATABASE_URL` | finngraph-etl 의 ETL Postgres 접속 URL (인사이트 기능이 원장·재무·캐시를 직접 읽음) |
| `BEDROCK_REGION` | 인사이트 기능의 Bedrock 리전 (기본 `us-east-1`) |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock API 키 (ETL 레포와 동일 발급분 사용 가능) |
| `BEDROCK_JUDGE_MODEL` | 후보 심사 모델 (기본 `us.anthropic.claude-sonnet-4-6`) |

> When running with Docker, `NEO4J_URI` and `DATABASE_URL` are automatically overridden inside the container to the finngraph-etl network service names (`bolt://neo4j:7687`, `db:5432`), so you can leave the `.env` values as the local ones.

## How to Run

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Docker.

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

```bash
uv run pytest
```
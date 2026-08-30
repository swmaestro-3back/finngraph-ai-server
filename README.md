# finngraph-kg-api

REST API Server for financial knowledge graph which is created by triplet extraction pipeline in `finngraph-etl` repository.

Supports only `GET` methods - used exclusively in the knowledge graph explorer.

## Project Overview

Finngraph KG API exposes a **financial knowledge graph** stored in Neo4j over a REST API.

The graph connects entities such as stocks (KOSPI / KOSDAQ / NYSE / NASDAQ), themes, commodities, products and countries through relationships like supply chains, exports, acquisitions,
investments, and competition.

Each read endpoint returns a **subgraph** (nodes + relationships) centered on the requested
entity, which a client can render as an interactive graph. Edge details (full provenance such as
source news and sentences) are fetched lazily per relationship.

**API endpoints** (all prefixed with `/api/v1`):

| Method & Path | Description |
| --- | --- |
| `GET /stock/{ticker}` | Subgraph within 3 hops of the given stock |
| `GET /theme/{name}` | Subgraph centered on a theme |
| `GET /product/{name}` | Subgraph centered on a product |
| `GET /commodity/{name}` | Subgraph centered on a commodity |
| `GET /relationship/{element_id}` | Full detail (provenance) of a single relationship |
| `GET /news/{news_id}/beneficiaries` | 뉴스 사건의 수혜 종목을 극성 2트랙(공급망/경쟁사)으로 추천. 매 호출 ~20초 동기 생성 (캐시 없음) |

## Directory Structure

```
finngraph-kg-api/
├── app/
│   ├── main.py               # FastAPI app entrypoint (lifespan, router mounting)
│   ├── crud.py               # Neo4j query functions (subgraph / relationship lookups)
│   ├── models.py             # Graph domain enums (NodeLabel, RelationshipType)
│   ├── schemas.py            # Pydantic response schemas (GraphResponse, ...)
│   ├── api/
│   │   ├── main.py           # Aggregates all route routers into api_router
│   │   └── routes/           # Endpoint handlers
│   │       ├── stock.py
│   │       ├── theme.py
│   │       ├── product.py
│   │       ├── commodity.py
│   │       └── relationship.py
│   ├── core/
│   │   ├── config.py         # Settings loaded from .env (pydantic-settings)
│   │   ├── db.py             # Neo4j async driver (singleton)
│   │   └── logger.py         # Logging setup
│   └── scripts/
│       └── seed.py           # Seed data for Neo4j
├── Dockerfile                # API image build
├── docker-compose.yml        # api service (Neo4j·Postgres 는 finngraph-etl 스택 공유)
├── pyproject.toml            # Project metadata & dependencies (uv)
└── .env.example              # Environment variable template
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
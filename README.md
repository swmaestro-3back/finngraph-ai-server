# finngraph-kg-api

REST API Server for financial knowledge graph which is created by triplet extraction pipeline in `finngraph-etl` repository.

Supports only `GET` methods - used exclusively in the knowledge graph explorer.

## Project Overview

Finngraph KG API exposes a **financial knowledge graph** stored in Neo4j over a REST API.

The graph has exactly two node labels and two relationship types:

- `(:Company)` — KOSPI / KOSDAQ listed companies
- `(:Theme)` — investment themes
- `(:Company)-[:SUPPLIES_TO]->(:Company)` — supply chain, with news / disclosure provenance
- `(:Company)-[:BELONGS_TO]->(:Theme)` — theme membership, with a `reason`

Each read endpoint returns the nodes and relationships it covers, which a client can render as an
interactive graph. Relationship provenance (source news and disclosures) is inlined in the
response, so no follow-up fetch is needed.

## Directory Structure

```
finngraph-kg-api/
├── app/
│   ├── main.py               # FastAPI app entrypoint (lifespan, router mounting)
│   ├── repository.py         # Neo4j READ 계층 (Cypher 정의 + 실행, 스키마 변환 위임)
│   ├── mappers.py            # neo4j Record/Node/Relationship → 응답 스키마 변환
│   ├── schemas.py            # Pydantic response schemas (SupplyChainResponse, ThemeResponse)
│   ├── graph.py              # Graph schema constants (NodeLabel, RelationshipType)
│   ├── enums.py              # API-facing enums (Market, MarketIndex)
│   ├── api/
│   │   ├── main.py           # Aggregates all route routers into api_router
│   │   └── routes/           # Endpoint handlers
│   │       ├── company.py
│   │       └── theme.py
│   ├── core/
│   │   ├── config.py         # Settings loaded from .env (pydantic-settings)
│   │   ├── db.py             # Neo4j async driver (singleton)
│   │   └── logger.py         # Logging setup
├── Dockerfile                # API image build
├── docker-compose.yml        # api service (Neo4j는 ETL 스택 공유)
├── pyproject.toml            # Project metadata & dependencies (uv)
└── .env.example              # Environment variable template
```

## Environment Variables

Copy .env.example to .env and fill in every value — Settings in app/core/config.py has no defaults, so a missing variable fails fast with a ValidationError at startup, even for variables you don't think you need (e.g. LangSmith tracing, or the API key of the LLM provider you aren't using).

```bash
cp .env.example .env
```

All variables are declared in [`app/core/config.py`](app/core/config.py) (pydantic-settings), which
loads them from `.env` at import time. Field names map to the upper-cased variable names below.

> `.env.example` ships placeholders only. Keep real credentials in `.env`, which is gitignored — never commit them.

## How to Run

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Docker.

### 1. Install dependencies

```bash
uv sync
```

### 2. Run with Docker

- API: http://localhost:8000
- **Swagger UI: http://localhost:8000/docs**
- ReDoc: http://localhost:8000/redoc
- Neo4j Browser: http://localhost:7474

Builds and starts both the API server and Neo4j.

```bash
docker compose up -d
```

The image is not rebuilt automatically after you change the source, so always pass `--build`.

```bash
docker compose up -d --build
```

Use the commands below to check status, view logs, or stop containers:

```bash
# check status
docker compose ps

# tail api logs
docker compose logs -f api

# stop
docker compose down

# stop and delete the Neo4j data volume
docker compose down -v
```

## Testing

```bash
uv run pytest
```
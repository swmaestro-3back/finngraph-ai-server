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
├── Dockerfile                # API image build
├── docker-compose.yml        # api service (Neo4j는 ETL 스택 공유)
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

> When running with Docker, `NEO4J_URI` is automatically overridden to `bolt://neo4j:7687` inside the container, so you can leave the `.env` value as the local one.

## How to Run

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Docker.

### 1. Install dependencies

```bash
uv sync
```

### 2. Run with Docker

Builds and starts both the API server and Neo4j.

```bash
docker compose up -d --build
```

- API: http://localhost:8000
- **Swagger UI: http://localhost:8000/docs**
- ReDoc: http://localhost:8000/redoc
- Neo4j Browser: http://localhost:7474

The image is not rebuilt automatically after you change the source, so always pass `--build`.

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
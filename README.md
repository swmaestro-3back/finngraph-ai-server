# finngraph-ai-server

REST API Server for financial knowledge graph which is created by triplet extraction pipeline in `finngraph-etl` repository.

Supports only READ-ONLY `GET` methods - used exclusively in the knowledge graph explorer.

## Project Overview

Finngraph AI Server exposes a **financial knowledge graph** stored in Neo4j over a REST API.

The API covers three node labels and five relationship types:

- `(:Company)` — KOSPI / KOSDAQ listed companies
- `(:Theme)` — investment themes
- `(:Event)` — news clusters (title, keywords, member news ids, publish window)
- `(:Company)-[:SUPPLIES_TO]->(:Company)` — supply chain, with news / disclosure provenance
- `(:Company)-[:ACQUIRES]->(:Company)`, `(:Company)-[:INVESTS_IN]->(:Company)` — same provenance properties as `SUPPLIES_TO`
- `(:Company)-[:BELONGS_TO]->(:Theme)` — theme membership, with a `reason`
- `(:Company)-[:HAS_EVENT]->(:Event)` — a company mentioned in an event (no properties)

Each read endpoint returns the nodes and relationships it covers, which a client can render as an
interactive graph. Relationship provenance (source news and disclosures) is inlined in the
response, so no follow-up fetch is needed.

## Directory Structure

```
finngraph-ai-server/
├── app/
│   ├── main.py               # FastAPI app entrypoint (lifespan, router mounting)
│   ├── repository.py         # Neo4j READ 계층 (Cypher 정의 + 실행, 스키마 변환 위임)
│   ├── mappers.py            # neo4j Record/Node/Relationship → 응답 스키마 변환
│   ├── schemas.py            # Pydantic response schemas (CompanyResponse, SupplyChainResponse, CompanyEventsResponse, ThemeResponse)
│   ├── graph.py              # Graph schema constants (NodeLabel, RelationshipType)
│   ├── enums.py              # API-facing enums (Market, MarketIndex)
│   ├── api/
│   │   ├── main.py           # Aggregates all route routers into api_router
│   │   └── routes/           # Endpoint handlers
│   │       ├── company.py
│   │       ├── theme.py
│   │       └── news.py
│   ├── beneficiary/          # 수혜주 추천 에이전트 기능
│   │   ├── schemas.py        # HTTP 응답 계약
│   │   ├── service.py        # 유스케이스 — HTTP 계약을 아는 유일한 곳
│   │   ├── repository.py     # Postgres·Neo4j 조회
│   │   ├── models.py         # 도메인 모델 + LLM 구조화 출력 계약
│   │   └── agent/            # LangGraph 본체 — FastAPI 를 모른다
│   │       ├── workflow.py   # 그래프 조립·라우팅 (팬아웃/팬인)
│   │       ├── state.py
│   │       ├── nodes/        # 공통 단계 노드 (planner/candidate_selector/finance_collector/evaluator)
│   │       ├── subgraphs/    # 병렬 트랙 서브그래프 (supply/, theme/ — 각자 nodes·state·graph)
│   │       ├── prompts/      # 시스템 프롬프트 + PROMPT_VERSION
│   │       └── utils/        # Bedrock 러너블·프롬프트 패킹·출력 후처리
│   ├── core/
│   │   ├── config.py         # Settings loaded from .env (pydantic-settings)
│   │   ├── db.py             # Neo4j async driver (singleton)
│   │   ├── postgres.py       # PostgresClient — async 커넥션 풀 싱글톤 (수혜주 기능용)
│   │   ├── graph_schema.py   # 수혜주 기능의 그래프 어휘 (NodeLabel, RelationshipType, MARKETS)
│   │   └── logger.py         # Logging setup
├── tests/
│   └── beneficiary/          # 단위 테스트 + 통합 테스트(`integration` 마커, 로컬 DB 필요)
├── Dockerfile                # API image build
├── docker-compose.yml        # api service (Neo4j·Postgres 는 finngraph-etl 스택 공유)
├── pyproject.toml            # Project metadata & dependencies (uv)
└── .env.example              # Environment variable template
```

## Environment Variables

Copy .env.example to .env and fill in every value — the `NEO4J_*` settings in app/core/config.py have no defaults, so a missing one fails fast with a ValidationError at startup.

```bash
cp .env.example .env
```

All variables are declared in [`app/core/config.py`](app/core/config.py) (pydantic-settings), which
loads them from `.env` at import time. Field names map to the upper-cased variable names below.

> `.env.example` ships placeholders only. Keep real credentials in `.env`, which is gitignored — never commit them.

| Variable | Description |
| --- | --- |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | 지식그래프 Neo4j 접속 정보 |
| `DATABASE_URL` | finngraph-etl 의 ETL Postgres 접속 URL (종목·테마 시세, 이벤트 메타, 간선 근거 기사·공시를 읽음) |

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

- API: http://localhost:8000
- **Swagger UI: http://localhost:8000/docs**
- ReDoc: http://localhost:8000/redoc
- Neo4j Browser: http://localhost:7474 (finngraph-etl 스택이 노출)

Builds and starts the API server (it joins the `finngraph-etl_default` network).

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

# stop (Neo4j·Postgres 는 finngraph-etl 소관이라 여기서 내려가지 않는다)
docker compose down
```

## Testing

단위 테스트만 — DB 없이 어디서나 돈다.

```bash
uv run pytest -m "not integration"
```

통합 테스트까지 포함하려면 finngraph-etl 의 Postgres 가 떠 있어야 한다
(`integration` 마커가 붙은 `test_rdb_integration.py` 가 실제 DB 를 읽는다). 마커를
걸지 않은 `uv run pytest` 는 이것까지 같이 돌리므로, DB 가 없으면 실패한다.

```bash
cd ../finngraph-etl && docker compose up -d db neo4j neo4j-init
cd - && uv run pytest
```

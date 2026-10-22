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

요청은 `api/routes → service → repository` 세 층을 지난다. 라우트는 `service` 의 `get_*` 만 부르고,
`service` 가 Neo4j·Postgres 조회를 엮어 응답 모델 하나를 완성하며, `repository` 는 저장소별·도메인별로
쿼리 하나씩만 실행한다.

```
finngraph-ai-server/
├── app/
│   ├── main.py               # FastAPI 앱 (lifespan: Neo4j 드라이버·Postgres 풀, /health)
│   ├── schemas.py            # Pydantic 응답 모델
│   ├── enums.py              # API 쿼리 파라미터 enum (Market, MarketIndex)
│   ├── api/
│   │   ├── main.py           # 라우터 묶음 (api_router)
│   │   ├── cache.py          # 성공 응답 Cache-Control
│   │   └── routes/           # 엔드포인트 — company, theme, news, relationship, event
│   ├── service/              # 응답 조립 — 도메인별로 routes 와 1:1
│   │   ├── company.py        #   기업 그래프·공급망 (+ 시세 enrich)
│   │   ├── theme.py          #   테마·소속 테마 (+ 시세 enrich)
│   │   ├── event.py          #   이벤트 서브그래프, 이벤트 상세(PG 3쿼리 + 시세)
│   │   ├── relationship.py   #   간선 근거(Neo4j 참조 → PG 기사·공시)
│   │   ├── news.py           #   뉴스 그래프 (시드 → 확장 → 보강, NewsGraphAccumulator)
│   │   ├── enrich.py         #   그래프 응답 노드에 종목·테마 시세, 이벤트 메타를 붙임
│   │   └── common.py         #   PG 커넥션 대기 상한
│   ├── repository/
│   │   ├── neo4j/            # Cypher + Record → 스키마 변환
│   │   │   ├── mappers.py    #   Node/Relationship/Path → 응답 스키마
│   │   │   ├── company.py, theme.py, event.py, relationship.py, news.py
│   │   └── postgres/         # SQL — 커넥션을 받아 dict 행만 돌려줌
│   │       ├── base.py       #   fetch_all/fetch_one, 값 변환(Decimal·date)
│   │       ├── quote.py, event.py, news.py, disclosure.py
│   └── core/
│       ├── config.py         # Settings (.env, pydantic-settings)
│       ├── db.py             # Neo4j async driver 싱글톤
│       ├── postgres.py       # PostgresClient — async 커넥션 풀 싱글톤
│       ├── graph.py          # 그래프 어휘 (NodeLabel, RelationshipType)
│       └── logger.py
├── tests/                    # 단위 테스트 + `integration` 마커(로컬 ETL DB 필요)
├── Dockerfile
├── compose.yaml              # api service (Neo4j·Postgres 는 finngraph-etl 스택 공유)
├── pyproject.toml
└── .env.example
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
(`integration` 마커가 붙은 `test_postgres_repository_integration.py` 가 실제 DB 를 읽는다). 마커를
걸지 않은 `uv run pytest` 는 이것까지 같이 돌리므로, DB 가 없으면 실패한다.

```bash
cd ../finngraph-etl && docker compose up -d db neo4j neo4j-init
cd - && uv run pytest
```

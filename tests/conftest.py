"""테스트 환경 주입.

Settings 가 import 시점에 .env 를 요구하므로(neo4j_* 필수 필드), .env 가 없는
환경에서도 테스트가 돌도록 최소 값을 주입한다. 환경변수는 pydantic-settings
에서 .env 보다 우선이라, .env 가 있으면 주입하지 않는다 — 여기서 setdefault
하면 실제 접속 정보를 더미 값으로 덮어쓴다. CI env 는 setdefault 라 항상 이긴다.

DATABASE_URL 기본값은 finngraph-etl 로컬 DB(docker compose up -d db)의 노출
포트(15432)다 — integration 테스트는 그 DB 에 마이그레이션이 적용돼 있어야 한다.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_DEFAULTS = {
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "test-only",
    "NEO4J_DATABASE": "finngraph",
    "DATABASE_URL": "postgresql://threeback:12345678@localhost:15432/finngraph",
}

if not (Path(__file__).resolve().parent.parent / ".env").exists():
    for _key, _value in _ENV_DEFAULTS.items():
        os.environ.setdefault(_key, _value)

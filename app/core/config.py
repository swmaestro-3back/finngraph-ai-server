from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str

    # === Postgres (finngraph-etl 이 소유하는 ETL DB) ===
    # 그래프 응답에 붙이는 종목·테마 시세, 이벤트 메타, 간선 근거 기사·공시를 여기서 읽는다.
    # 기본값은 로컬 `docker compose up -d db`(finngraph-etl)의 노출 포트에 맞춘 것이다.
    database_url: str = "postgresql://threeback:12345678@localhost:15432/finngraph"


settings = Settings()

import os

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
    # BELONGS_TO.reason_embedding 에 걸린 관계 벡터 인덱스 이름 (Neo4j 5.18+)
    neo4j_reason_vector_index: str = "belongs_to_reason_embedding"

    # === Postgres (finngraph-etl 이 소유하는 ETL DB) ===
    # 인사이트 기능은 원장(relation_sources)·재무를 RDB 에서 직접 읽는다.
    # 기본값은 로컬 `docker compose up -d db`(finngraph-etl)의 노출 포트에 맞춘 것이다.
    database_url: str = "postgresql://threeback:12345678@localhost:15432/finngraph"

    # === Bedrock ===
    # 인사이트 기능용. 모델 id 는 계정에 활성화된 인퍼런스 프로파일 기준.
    bedrock_region: str = "us-east-1"
    aws_bearer_token_bedrock: str = ""
    bedrock_evaluator_model: str = "us.anthropic.claude-sonnet-4-6"
    # beneficiary 에이전트의 계획·선별용 경량 모델 (버전 접미사 필수)
    bedrock_light_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    # theme 트랙의 reason 벡터 검색용 — finngraph-etl 이 reason_embedding 을 만들 때
    # 쓴 모델과 반드시 같아야 한다(pipelines/common/config.py). 다르면 벡터가 비교 불가능하다.
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    bedrock_hypothesis_model: str | None = None

    # === LangSmith (LLM·워크플로우 트레이싱) ===
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "finngraph"


settings = Settings()

# The LangSmith SDK reads os.environ only, never constructor arguments, so copy the values
# across once at import time. Module caching keeps this to a single run per process.
if settings.langsmith_tracing:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    pydantic-settings로 .env를 읽어 타입 검증된 설정 객체를 만든다.
    환경변수가 필요한 코드는 os.getenv가 아니라 이 settings 인스턴스를 import해서 쓴다.
    """

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
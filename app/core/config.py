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

    database_url: str | None = None

    bedrock_region: str = "us-east-1"
    aws_bearer_token_bedrock: str | None = None
    bedrock_embedding_model: str | None = None
    bedrock_hypothesis_model: str | None = None
    bedrock_evaluator_model: str | None = None

    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None


settings = Settings()
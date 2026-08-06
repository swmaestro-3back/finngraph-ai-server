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


settings = Settings()
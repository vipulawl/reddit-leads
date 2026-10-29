import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "web:reddit-leads:v0.1"
    reddit_refresh_token: str = ""

    typesafe_api_key: str = ""
    jev_model: str = "jev-latest"

    scorer: str = "auto"
    scorer_base_url: str = "http://localhost:11434/v1"
    scorer_api_key: str = "ollama"
    scorer_model: str = "llama3.2"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5-mini"

    jwt_secret: str = "dev-secret"
    database_url: str = "sqlite:///./data/leads.db"
    cors_origins: str = "http://localhost:3000"


settings = Settings()

if os.environ.get("IN_DOCKER"):
    for field in ("scorer_base_url", "llm_base_url"):
        value = getattr(settings, field)
        setattr(settings, field, value.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal"))

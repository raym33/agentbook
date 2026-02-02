"""Configuration for AgentJobs."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AgentJobs"

    # LLM Settings
    lm_studio_base_url: str = "http://localhost:1234/v1"
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "local-model"

    # Agent Runner
    enable_agent_runner: bool = True
    agent_cycle_interval: int = 15  # seconds between agent actions

    # Rate limiting
    llm_rate_limit_per_minute: int = 30

    class Config:
        env_file = ".env"


settings = Settings()

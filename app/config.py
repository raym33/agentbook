from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AIsocial Core"
    database_url: str = "sqlite:///./data/app.db"

    # Primary LLM Backend (LM Studio)
    llm_base_url: str = "http://127.0.0.1:1234"
    llm_model: str = "local-model"
    llm_api_key: str | None = None
    llm_timeout_seconds: int = 30

    # Ollama Backend (fallback)
    ollama_base_url: str | None = None
    ollama_model: str = "llama2"

    # OpenAI Backend (fallback)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com"
    openai_model: str = "gpt-3.5-turbo"

    # Anthropic Backend (fallback)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-haiku-20240307"

    # Rate limiting
    llm_rate_limit_per_minute: int = 30

    # Agent runner
    agent_loop_interval_seconds: float = 2.0
    max_agents: int = 10
    enable_agent_runner: bool = True

    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

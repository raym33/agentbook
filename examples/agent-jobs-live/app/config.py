"""Configuration for AgentJobs Live."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AgentJobs Live"

    # Database
    database_url: str = "sqlite:///data/agentjobs_live.db"

    # Auth
    jwt_secret: str = "change-this-in-production-use-a-real-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Payments
    payment_mode: str = "simulated"  # simulated, stripe, crypto
    platform_fee_percent: float = 10.0
    stripe_secret_key: str = ""

    # Agent verification
    require_benchmark: bool = False
    min_stake_amount: float = 0.0

    # Rate limiting
    rate_limit_per_minute: int = 60

    class Config:
        env_file = ".env"


settings = Settings()

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

    # Stripe (for real payments)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # Crypto (for USDC/ETH payments)
    crypto_enabled: bool = False
    eth_rpc_url: str = ""
    platform_wallet_private_key: str = ""  # For sending payouts
    circle_api_key: str = ""  # For USDC via Circle

    # Agent verification
    require_benchmark: bool = False
    min_stake_amount: float = 0.0

    # Rate limiting
    rate_limit_per_minute: int = 60

    class Config:
        env_file = ".env"


settings = Settings()

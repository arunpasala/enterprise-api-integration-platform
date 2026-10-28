from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    api_key: str = 'dev-local-key-change-me'
    database_url: str = 'sqlite:///./integration.db'
    partner_url: str = 'http://localhost:8000/mock-partner/customers'
    webhook_secret: str = 'change-me-in-production'
    worker_interval_seconds: float = 2
    max_attempts: int = 5
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()

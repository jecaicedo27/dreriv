"""
Configuration management for Deriv Trading Bot V2
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Deriv Trading Bot V2"
    DEBUG: bool = False
    
    # Deriv API
    DERIV_API_TOKEN: str
    DERIV_APP_ID: str
    DERIV_ACCOUNT_TYPE: str = "demo"
    
    # Groq API
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_TEMPERATURE: float = 0.05
    GROQ_MAX_TOKENS: int = 1500
    GROQ_TIMEOUT_SECONDS: int = 8
    
    # Database
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DATABASE_URL: str
    
    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: str
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    
    # Dashboard
    DASHBOARD_ADMIN_EMAIL: str
    DASHBOARD_ADMIN_PASSWORD: str
    JWT_SECRET: str
    
    # Risk Management
    KELLY_FRACTION: float = 0.25
    MAX_DAILY_LOSS_PCT: float = 8.0
    MAX_DRAWDOWN_PCT: float = 25.0
    MAX_CONCURRENT_TRADES: int = 3
    MAX_CORRELATED_TRADES: int = 2
    MAX_TRADES_PER_DAY: int = 40
    COOLDOWN_AFTER_LOSSES: int = 3
    COOLDOWN_MINUTES: int = 15
    
    # Feature Flags
    USE_GROQ_LAYER2: bool = False  # Toggle AI meta-analysis layer
    ENABLE_PGVECTOR: bool = False
    ENABLE_AB_TESTING: bool = True
    ENABLE_DRAWDOWN_RECOVERY: bool = True
    ENABLE_GROQ_FALLBACK: bool = True
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "/var/log/deriv-bot/bot.log"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

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
    
    # OpenAI API
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.2"
    OPENAI_TEMPERATURE: float = 0.05
    OPENAI_MAX_TOKENS: int = 1500
    OPENAI_TIMEOUT_SECONDS: int = 15
    
    # Claude (Anthropic) API
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-4-20250514"
    CLAUDE_TEMPERATURE: float = 0.05
    CLAUDE_MAX_TOKENS: int = 1500
    CLAUDE_TIMEOUT_SECONDS: int = 15
    
    # Gemini (Google) API
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TEMPERATURE: float = 0.05
    GEMINI_MAX_TOKENS: int = 1500
    GEMINI_TIMEOUT_SECONDS: int = 15
    
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
    MAX_TRADES_PER_DAY: int = 600
    COOLDOWN_AFTER_LOSSES: int = 10
    COOLDOWN_MINUTES: int = 5
    MIN_STAKE: float = 10.0  # Minimum stake during progressive reduction
    
    # Feature Flags
    USE_GROQ_LAYER2: bool = True  # Groq decides on L1 signals
    ENABLE_PGVECTOR: bool = False
    ENABLE_AB_TESTING: bool = True
    ENABLE_DRAWDOWN_RECOVERY: bool = True
    ENABLE_GROQ_FALLBACK: bool = True
    
    # Engine Selection (original_v1, university_v2, bullish_v3, bullish_v4, reversal_v5, bearish_v6)
    ENGINE_NAME: str = "bullish_v4"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "/var/log/deriv-bot/bot.log"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

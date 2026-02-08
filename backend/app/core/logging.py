"""
Logging configuration for Deriv Trading Bot
"""
import sys
from loguru import logger
from app.core.config import get_settings

settings = get_settings()


def setup_logging():
    """
    Configure loguru logger with file and console output
    """
    # Remove default handler
    logger.remove()
    
    # Console handler (colored)
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=settings.LOG_LEVEL,
        colorize=True
    )
    
    # File handler (JSON format for production)
    logger.add(
        settings.LOG_FILE,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=settings.LOG_LEVEL,
        rotation="100 MB",
        retention="30 days",
        compression="gz"
    )
    
    logger.info(f"✅ Logging configured - Level: {settings.LOG_LEVEL}")
    return logger

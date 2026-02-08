"""
Data Feeder Service
Dedicated process for collecting ticks and building candles.
Decoupled from the trading bot to ensure data continuity during restarts.
"""
import asyncio
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.services.deriv_client import deriv_client
from app.services.data_collector import DataCollector
from app.services.telegram_notifier import telegram_notifier

settings = get_settings()

class DataFeeder:
    """
    Dedicated Data Ingestion Service
    - Connects to Deriv
    - Subscribes to ticks
    - Feeds DataCollector -> DB
    """
    
    def __init__(self):
        self.db: Session = SessionLocal()
        self.symbol = "R_100"
        self.timeframe_seconds = 60
        self.data_collector = DataCollector(self.db, self.symbol, self.timeframe_seconds)
        self.is_running = False

    async def start(self):
        """Start the feeder service"""
        logger.info("📡 Starting Data Feeder Service...")
        
        # Connect to Deriv
        if not await deriv_client.connect():
            logger.critical("❌ Failed to connect (Feeder)")
            return

        self.is_running = True
        deriv_client.running = True
        
        # Start handler task (Required for Auth)
        logger.info("🔄 Feeder entering message loop...")
        handler_task = asyncio.create_task(deriv_client.message_handler_loop())
        
        # Authorize
        if not await deriv_client.authorize():
            logger.critical("❌ Failed to authorize with Deriv (Feeder)")
            return

        # Set tick callback
        deriv_client.set_tick_callback(self._on_tick)
        
        # Subscribe
        logger.info(f"📊 Feeder subscribing to {self.symbol}...")
        await deriv_client.subscribe_to_ticks(self.symbol)
        
        # Notify
        # await telegram_notifier.send_message("📡 Data Feeder Grid Started")

        # Wait for handler (keeps script running)
        await handler_task

    async def _on_tick(self, tick_data: dict):
        """Handle incoming ticks"""
        # Pass to collector for DB storage
        await self.data_collector.process_tick(tick_data)

async def main():
    feeder = DataFeeder()
    try:
        await feeder.start()
    except KeyboardInterrupt:
        logger.warning("⚠️ Feeder interrupted")
    except Exception as e:
        logger.critical(f"🚨 Feeder fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

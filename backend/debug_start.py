
import sys
import logging
import asyncio
from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.append("/app")

print("1. Importing modules...")
try:
    from app.core.database import SessionLocal, engine
    from app.models.models import BotState
    print("✅ Modules imported")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

def test_db_sync():
    print("2. Testing Sync DB Connection...")
    try:
        db = SessionLocal()
        print("   - Session created")
        
        print("   - Querying BotState...")
        state = db.query(BotState).filter(BotState.id == 1).first()
        print(f"✅ Sync Query success. State: {state}")
        db.close()
    except Exception as e:
        print(f"❌ Sync DB failed: {e}")

async def test_async_start():
    print("3. Testing Async Method...")
    try:
        from app.bot import TradingBot
        print("   - Instantiating Bot...")
        bot = TradingBot()
        print("   - Calling _initialize_state...")
        await bot._initialize_state()
        print("✅ _initialize_state success")
    except Exception as e:
        print(f"❌ Async test failed: {e}")

if __name__ == "__main__":
    test_db_sync()
    asyncio.run(test_async_start())

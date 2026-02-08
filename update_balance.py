"""
Quick script to fetch current balance from Deriv and update bot_state
"""
import asyncio
from app.services.deriv_client import deriv_client
from app.core.database import SessionLocal
from app.models.models import BotState

async def update_balance():
    # Connect to Deriv
    await deriv_client.connect()
    
    # Start message handler
    deriv_client.running = True
    asyncio.create_task(deriv_client.message_handler_loop())
    
    # Authorize and get balance
    auth_data = await deriv_client.authorize()
    
    if auth_data:
        balance = float(auth_data.get('balance', 0))
        currency = auth_data.get('currency', 'USD')
        is_virtual = auth_data.get('is_virtual', True)
        
        print(f"✅ Account Type: {'DEMO' if is_virtual else 'REAL'}")
        print(f"💰 Current Balance: {balance} {currency}")
        
        # Update database
        db = SessionLocal()
        bot_state = db.query(BotState).filter(BotState.id == 1).first()
        
        if bot_state:
            bot_state.balance = balance
            bot_state.initial_balance = balance
            bot_state.peak_balance = balance
            bot_state.trades_today = 0
            bot_state.wins_today = 0
            bot_state.losses_today = 0
            bot_state.daily_pnl = 0
            bot_state.losses_consecutive = 0
            bot_state.cooldown_until = None
            bot_state.cooldown_reason = None
            bot_state.last_trade_date = None
            
            db.commit()
            print(f"✅ Bot state updated with balance: ${balance}")
        else:
            print("❌ Bot state not found")
        
        db.close()
    else:
        print("❌ Failed to authorize with Deriv")
    
    await deriv_client.stop()

if __name__ == "__main__":
    asyncio.run(update_balance())

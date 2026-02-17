"""
Recovery Script: Close Pending Trades
Fetches final status of PENDING trades from Deriv API and updates database
"""
import asyncio
import websockets
import json
import sys
import os
from datetime import datetime, timezone, timedelta

# Add app to path
sys.path.insert(0, '/app')

from app.core.database import get_db
from app.core.config import get_settings

settings = get_settings()



async def get_contract_status(contract_id: str) -> dict:
    """Fetch contract result from Deriv API"""
    url = f"wss://ws.derivws.com/websockets/v3?app_id={settings.DERIV_APP_ID}"
    
    async with websockets.connect(url) as ws:
        # First authorize
        auth_request = {
            "authorize": settings.DERIV_API_TOKEN
        }
        await ws.send(json.dumps(auth_request))
        auth_response = await ws.recv()
        auth_data = json.loads(auth_response)
        
        if "error" in auth_data:
            print(f"❌ Authorization error: {auth_data['error']}")
            return None
        
        # Request contract details
        request = {
            "proposal_open_contract": 1,
            "contract_id": int(contract_id)
        }
        await ws.send(json.dumps(request))
        
        response = await ws.recv()
        data = json.loads(response)
        
        if "error" in data:
            print(f"❌ Error fetching contract {contract_id}: {data['error']}")
            return None
        
        return data.get("proposal_open_contract")


async def close_pending_trade(session, trade):
    """Close a single pending trade"""
    try:
        contract_data = await get_contract_status(trade.deriv_contract_id)
        
        if not contract_data:
            print(f"⚠️ Could not fetch contract {trade.deriv_contract_id}")
            return False
        
        status = contract_data.get("status")
        sell_price = float(contract_data.get("sell_price", 0))
        buy_price = float(contract_data.get("buy_price", 0))
        profit = sell_price - buy_price
        
        # Determine outcome
        if status in ["sold", "won"]:
            outcome = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")
        elif status == "lost":
            outcome = "LOSS"
        else:
            print(f"⚠️ Contract {trade.deriv_contract_id} still active (status: {status})")
            return False
        
        # Get exit price
        exit_tick = float(contract_data.get("exit_tick", 0)) or float(contract_data.get("current_spot", 0))
        
        # Update trade
        trade.outcome = outcome
        trade.exit_price = exit_tick
        trade.profit_loss = profit
        trade.exit_time = datetime.now(timezone.utc)
        trade.updated_at = datetime.now(timezone.utc)
        
        session.commit()
        
        print(f"✅ Closed trade {str(trade.id)[:8]}... → {outcome} ({profit:+.2f} USD)")
        return True
        
    except Exception as e:
        print(f"❌ Error closing trade {trade.id}: {e}")
        session.rollback()
        return False


async def main():
    from app.models.models import Trade
    
    # Get database session from app
    db = next(get_db())
    
    try:
        # Get ALL PENDING trades (no date filter)
        pending_trades = db.query(Trade).filter(
            Trade.outcome == "PENDING"
        ).all()
        
        print(f"🔍 Found {len(pending_trades)} PENDING trades")
        
        closed_count = 0
        for trade in pending_trades:
            if await close_pending_trade(db, trade):
                closed_count += 1
            await asyncio.sleep(0.5)  # Rate limiting
        
        print(f"\n✅ Successfully closed {closed_count}/{len(pending_trades)} trades")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

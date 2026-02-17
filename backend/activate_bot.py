#!/usr/bin/env python3
"""Activate the trading bot"""
import sys
sys.path.insert(0, '/app')

from app.core.database import SessionLocal
from app.models.models import BotState
from datetime import datetime

db = SessionLocal()

try:
    state = db.query(BotState).first()
    
    if not state:
        print("❌ No bot state found in database!")
        sys.exit(1)
    
    print(f"\n🤖 CURRENT BOT STATE:")
    print(f"   Trading Enabled: {state.is_trading_enabled}")
    print(f"   Balance: ${state.balance:.2f}")
    print(f"   Trades Today: {state.trades_today}")
    print(f"   Daily P&L: ${state.daily_pnl:.2f}")
    print(f"   Losses Consecutive: {state.losses_consecutive}")
    print(f"   Cooldown: {state.cooldown_until}")
    
    if state.is_trading_enabled:
        print(f"\n⚠️  Bot is already RUNNING!")
    else:
        # Activate bot
        state.is_trading_enabled = True
        state.cooldown_until = None      # Clear any cooldown
        state.cooldown_reason = None
        db.commit()
        
        print(f"\n✅ BOT ACTIVATED!")
        print(f"   Trading enabled: TRUE")
        print(f"   Cooldown cleared")
        print(f"   Ready to trade!")
        
finally:
    db.close()

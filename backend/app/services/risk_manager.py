"""
Risk Management Module
Implements comprehensive risk controls for the trading bot

Based on skill: trading-risk-management
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import BotState

settings = get_settings()


class RiskManager:
    """
    Comprehensive risk management system
    
    Features:
    - Daily loss limits
    - Maximum drawdown limits
    - Progressive drawdown recovery
    - Consecutive loss cooldowns
    - Maximum concurrent trades
    - Circuit breakers
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.bot_state = self._get_bot_state()
    
    def _get_bot_state(self) -> BotState:
        """Get current bot state from database"""
        state = self.db.query(BotState).filter(BotState.id == 1).first()
        if not state:
            # Initialize if doesn't exist
            state = BotState(
                id=1,
                balance=0,
                initial_balance=0,
                peak_balance=0
            )
            self.db.add(state)
            self.db.commit()
        return state
    
    def refresh_state(self):
        """Refresh bot state from database"""
        self.db.refresh(self.bot_state)
    
    def can_trade(self) -> Dict[str, Any]:
        """
        Check if bot can execute a new trade
        
        Returns:
            Dict with allowed (bool) and reason (str)
        """
        self.refresh_state()
        
        # Check if trading is enabled
        if not self.bot_state.is_trading_enabled:
            return {
                'allowed': False,
                'reason': 'Trading manually disabled',
                'severity': 'WARNING'
            }
        
        # Check cooldown
        if self.bot_state.cooldown_until:
            if datetime.now() < self.bot_state.cooldown_until:
                remaining = (self.bot_state.cooldown_until - datetime.now()).total_seconds() / 60
                return {
                    'allowed': False,
                    'reason': f'In cooldown for {remaining:.1f} more minutes - {self.bot_state.cooldown_reason}',
                    'severity': 'INFO'
                }
        
        # Check daily loss limit
        daily_loss_pct = abs(self.bot_state.daily_pnl / self.bot_state.balance * 100) if self.bot_state.balance > 0 else 0
        
        if self.bot_state.daily_pnl < 0 and daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            return {
                'allowed': False,
                'reason': f'Daily loss limit reached ({daily_loss_pct:.1f}% >= {settings.MAX_DAILY_LOSS_PCT}%)',
                'severity': 'CRITICAL'
            }
        
        # Check maximum drawdown
        if self.bot_state.current_drawdown_pct >= settings.MAX_DRAWDOWN_PCT:
            return {
                'allowed': False,
                'reason': f'Maximum drawdown reached ({self.bot_state.current_drawdown_pct:.1f}% >= {settings.MAX_DRAWDOWN_PCT}%)',
                'severity': 'CRITICAL'
            }
        
        # Check consecutive losses
        if self.bot_state.losses_consecutive >= settings.COOLDOWN_AFTER_LOSSES:
            self._activate_cooldown(
                minutes=settings.COOLDOWN_MINUTES,
                reason=f'{self.bot_state.losses_consecutive} consecutive losses'
            )
            return {
                'allowed': False,
                'reason': f'Cooldown activated after {self.bot_state.losses_consecutive} consecutive losses',
                'severity': 'WARNING'
            }
        
        # Check daily trade limit
        if self.bot_state.trades_today >= settings.MAX_TRADES_PER_DAY:
            return {
                'allowed': False,
                'reason': f'Daily trade limit reached ({self.bot_state.trades_today}/{settings.MAX_TRADES_PER_DAY})',
                'severity': 'INFO'
            }
        
        # All checks passed
        return {
            'allowed': True,
            'reason': 'All risk checks passed',
            'severity': 'INFO'
        }
    
    def _activate_cooldown(self, minutes: int, reason: str):
        """Activate cooldown period"""
        self.bot_state.cooldown_until = datetime.now() + timedelta(minutes=minutes)
        self.bot_state.cooldown_reason = reason
        self.db.commit()
        logger.warning(f"⏸️ Cooldown activated for {minutes} minutes: {reason}")
    
    def get_drawdown_multiplier(self) -> float:
        """
        Calculate stake multiplier based on current drawdown
        Progressive recovery: reduce stake during drawdown
        
        Returns:
            Multiplier (0.5 - 1.0)
        """
        if not settings.ENABLE_DRAWDOWN_RECOVERY:
            return 1.0
        
        drawdown_pct = self.bot_state.current_drawdown_pct
        
        if drawdown_pct < 5:
            # No significant drawdown
            return 1.0
        elif drawdown_pct < 10:
            # 5-10% drawdown → 90% stake
            return 0.9
        elif drawdown_pct < 15:
            # 10-15% drawdown → 75% stake
            return 0.75
        elif drawdown_pct < 20:
            # 15-20% drawdown → 60% stake
            return 0.6
        else:
            # 20%+ drawdown → 50% stake (very conservative)
            return 0.5
    
    def update_balance(self, new_balance: float):
        """Update balance and recalculate metrics"""
        from decimal import Decimal
        
        # Ensure proper types
        current_balance = Decimal(str(new_balance))
        old_balance = self.bot_state.balance
        
        self.bot_state.balance = current_balance
        
        # Update peak balance
        if current_balance > self.bot_state.peak_balance:
            self.bot_state.peak_balance = current_balance
        
        # Recalculate drawdown
        if self.bot_state.peak_balance > 0:
            peak = self.bot_state.peak_balance
            diff = peak - current_balance
            self.bot_state.current_drawdown_pct = (diff / peak) * 100
        
        self.db.commit()
        logger.info(f"💰 Balance updated: {old_balance} → {current_balance} (DD: {self.bot_state.current_drawdown_pct:.1f}%)")
    
    def reset_daily_counters(self):
        """Reset daily counters (call at start of new trading day)"""
        today = datetime.now().date()
        
        if self.bot_state.last_trade_date != today:
            logger.info(f"📅 New trading day - resetting counters")
            self.bot_state.trades_today = 0
            self.bot_state.wins_today = 0
            self.bot_state.losses_today = 0
            self.bot_state.daily_pnl = 0
            self.bot_state.last_trade_date = today
            self.db.commit()
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Get current risk metrics summary"""
        self.refresh_state()
        
        daily_loss_pct = abs(self.bot_state.daily_pnl / self.bot_state.balance * 100) if self.bot_state.balance > 0 else 0
        
        return {
            'balance': float(self.bot_state.balance),
            'peak_balance': float(self.bot_state.peak_balance),
            'current_drawdown_pct': float(self.bot_state.current_drawdown_pct),
            'drawdown_multiplier': self.get_drawdown_multiplier(),
            'daily_pnl': float(self.bot_state.daily_pnl),
            'daily_loss_pct': round(daily_loss_pct, 2),
            'trades_today': self.bot_state.trades_today,
            'wins_today': self.bot_state.wins_today,
            'losses_today': self.bot_state.losses_today,
            'losses_consecutive': self.bot_state.losses_consecutive,
            'in_cooldown': self.bot_state.cooldown_until > datetime.now() if self.bot_state.cooldown_until else False,
            'trading_enabled': self.bot_state.is_trading_enabled
        }

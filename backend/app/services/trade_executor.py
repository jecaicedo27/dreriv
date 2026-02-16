"""
Trade Execution Engine
Handles execution of trades via Deriv WebSocket
"""
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from loguru import logger
from sqlalchemy.orm import Session

from app.models.models import Trade, BotState
from app.services.deriv_client import deriv_client
from app.services.kelly_criterion import KellyCriterion
from app.services.risk_manager import RiskManager
from app.services.telegram_notifier import telegram_notifier


class TradeExecutor:
    """
    Execute trades and manage trade lifecycle
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.risk_manager = RiskManager(db)
    
    async def execute_trade(
        self,
        signal: Dict[str, Any],
        balance: float
    ) -> Optional[Trade]:
        """
        Execute a trade based on analysis signal
        
        Args:
            signal: Signal from Layer1Engine
            balance: Current account balance
            
        Returns:
            Trade object if executed, None if rejected
        """
        # Check if trading is allowed
        risk_check = self.risk_manager.can_trade()
        
        if not risk_check['allowed']:
            logger.warning(f"⛔ Trade rejected: {risk_check['reason']}")
            
            if risk_check['severity'] in ['CRITICAL', 'WARNING']:
                await telegram_notifier.notify_risk_event(
                    'TRADE_REJECTED',
                    risk_check['reason']
                )
            
            return None
        
        # Extract signal data
        symbol = signal['symbol']
        contract_type = signal['contract_type']
        direction = signal['final_signal']  # 'CALL' or 'PUT'
        confidence = signal['final_confidence']
        duration = signal.get('duration', signal.get('suggested_duration', 300))  # Try 'duration' first, fallback to 'suggested_duration'
        
        # Calculate stake with Kelly Criterion
        stake_mult = signal.get('suggested_stake_multiplier', 1.0)
        drawdown_mult = self.risk_manager.get_drawdown_multiplier()
        
        stake_info = KellyCriterion.get_recommended_stake(
            balance=balance,
            confidence=confidence,
            stake_multiplier=stake_mult,
            drawdown_multiplier=drawdown_mult
        )
        
        stake = stake_info['stake']
        
        logger.info(f"🎯 Executing trade: {symbol} {direction} ${stake:.2f} ({duration}s)")
        
        # Execute via Deriv WebSocket
        contract = await deriv_client.buy_contract(
            symbol=symbol,
            contract_type=contract_type,
            amount=stake,
            duration=duration,
            duration_unit='s',
            basis='stake'
        )
        
        if not contract:
            logger.error("❌ Trade execution failed")
            return None
        
        # Create trade record
        trade = Trade(
            id=uuid.uuid4(),
            symbol=symbol,
            contract_type=contract_type,
            direction=direction,
            entry_time=datetime.now(),
            entry_price=signal['current_price'],
            stake=stake,
            duration_seconds=duration,
            outcome='PENDING',
            
            # Decision layers
            layer1_signal=direction,
            layer1_confidence=confidence,
            layer2_similar_patterns=None,  # Not used in MVP
            layer2_weighted_winrate=None,
            layer3_groq_used=signal.get('layer') == 'groq_layer2' or signal.get('groq_used', False),
            layer3_groq_confidence=signal.get('groq_confidence'),
            
            # Final decision
            final_confidence=confidence,
            concordance_score=1.0,  # Only Layer 1 in MVP
            
            # Risk management
            kelly_fraction=stake_info['base_kelly_stake'] / balance if balance > 0 else 0,
            drawdown_multiplier=drawdown_mult,
            
            # Deriv contract ID
            deriv_contract_id=contract.get('contract_id')
        )
        
        self.db.add(trade)
        self.db.commit()
        
        logger.success(f"✅ Trade saved: {trade.id}")
        
        # Send Telegram notification
        await telegram_notifier.notify_trade_opened({
            'symbol': symbol,
            'direction': direction,
            'stake': stake,
            'confidence': confidence,
            'duration_seconds': duration,
            'reasoning': signal['reasoning']
        })
        
        return trade
    
    async def close_trade(
        self,
        trade: Trade,
        outcome: str,
        exit_price: float,
        profit_loss: float
    ):
        """
        Close a trade and update records
        
        Args:
            trade: Trade object
            outcome: 'WIN' or 'LOSS'
            exit_price: Exit price
            profit_loss: Profit or loss amount
        """
        trade.outcome = outcome
        trade.exit_time = datetime.now()
        trade.exit_price = exit_price
        trade.profit_loss = profit_loss
        
        self.db.commit()
        
        logger.info(f"🏁 Trade closed: {outcome} ${profit_loss:+.2f}")
        
        # Update bot state (done automatically by trigger in database)
        # But let's refresh to get latest state
        self.risk_manager.refresh_state()
        
        # Send notification
        await telegram_notifier.notify_trade_closed({
            'symbol': trade.symbol,
            'outcome': outcome,
            'profit_loss': profit_loss,
            'balance': float(self.risk_manager.bot_state.balance)
        })



    async def check_pending_trades(self):
        """
        Check status of all pending trades and close if settled
        """
        try:
            # Get pending trades
            pending_trades = self.db.query(Trade).filter(
                Trade.outcome == 'PENDING'
            ).all()
            
            if not pending_trades:
                return
                
            for trade in pending_trades:
                try:
                    # Check status with Deriv
                    contract_id = int(trade.deriv_contract_id)
                    status_data = await deriv_client.get_contract_status(contract_id)
                    
                    if not status_data:
                        continue
                        
                    is_sold = status_data.get('is_sold')
                    is_expired = status_data.get('is_expired')
                    
                    if is_sold or is_expired:
                        # Extract outcome
                        profit = float(status_data.get('profit', 0))
                        status = status_data.get('status')  # won/lost
                        sell_price = float(status_data.get('sell_price', 0))
                        
                        outcome = 'BREAK_EVEN'
                        if profit > 0:
                            outcome = 'WIN'
                        elif profit < 0:
                            outcome = 'LOSS'
                        elif status == 'won':
                             outcome = 'WIN'
                        elif status == 'lost':
                             outcome = 'LOSS'
                             
                        # Close trade
                        await self.close_trade(
                            trade=trade,
                            outcome=outcome,
                            exit_price=sell_price,
                            profit_loss=profit
                        )
                        logger.success(f"✅ Stale trade {trade.id} settled via check: {outcome} {profit:+.2f}")
                        
                except Exception as e:
                    logger.error(f"❌ Error checking trade {trade.id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Error in check_pending_trades: {e}")

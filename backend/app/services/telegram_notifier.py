"""
Telegram Notification Service
Send trading alerts and updates via Telegram bot
"""
import httpx
from typing import Dict, Any
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


class TelegramNotifier:
    """
    Send notifications via Telegram Bot API
    """
    
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message to Telegram
        
        Args:
            text: Message text (supports Markdown)
            parse_mode: "Markdown" or "HTML"
            
        Returns:
            bool: True if sent successfully
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    logger.debug(f"✅ Telegram message sent")
                    return True
                else:
                    logger.error(f"❌ Telegram API error: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Telegram send error: {e}")
            return False
    
    async def notify_trade_opened(self, trade_data: Dict[str, Any]):
        """Notify when a trade is opened"""
        symbol = trade_data.get('symbol', 'UNKNOWN')
        direction = trade_data.get('direction', 'UNKNOWN')
        stake = trade_data.get('stake', 0)
        confidence = trade_data.get('confidence', 0)
        duration = trade_data.get('duration_seconds', 0)
        reasoning = trade_data.get('reasoning', 'No reason provided')
        
        message = f"""
🚀 *TRADE OPENED*

📊 Symbol: `{symbol}`
🎯 Direction: *{direction}*
💰 Stake: `${stake:.2f}`
⏱️ Duration: `{duration}s`
📈 Confidence: `{confidence*100:.1f}%`

💡 Reasoning:
_{reasoning}_
"""
        await self.send_message(message)
    
    async def notify_trade_closed(self, trade_data: Dict[str, Any]):
        """Notify when a trade is closed"""
        symbol = trade_data.get('symbol', 'UNKNOWN')
        outcome = trade_data.get('outcome', 'UNKNOWN')
        pnl = trade_data.get('profit_loss', 0)
        balance = trade_data.get('balance', 0)
        
        emoji = "✅" if outcome == "WIN" else "❌"
        
        message = f"""
{emoji} *TRADE CLOSED*

📊 Symbol: `{symbol}`
🎲 Outcome: *{outcome}*
💵 P&L: `${pnl:+.2f}`
💰 Balance: `${balance:.2f}`
"""
        await self.send_message(message)
    
    async def notify_risk_event(self, event_type: str, message: str):
        """Notify about risk management events"""
        emoji_map = {
            'COOLDOWN': '⏸️',
            'DAILY_LIMIT': '🚨',
            'DRAWDOWN': '📉',
            'CIRCUIT_BREAKER': '🛑'
        }
        
        emoji = emoji_map.get(event_type, '⚠️')
        
        telegram_msg = f"""
{emoji} *RISK EVENT*

Type: `{event_type}`

{message}
"""
        await self.send_message(telegram_msg)
    
    async def notify_bot_started(self):
        """Notify when bot starts"""
        message = f"""
🤖 *BOT STARTED*

Account: `{settings.DERIV_ACCOUNT_TYPE.upper()}`
Mode: `Layer 1 MVP`

✅ Ready to trade
"""
        await self.send_message(message)
    
    async def notify_daily_summary(self, summary: Dict[str, Any]):
        """Send daily performance summary"""
        trades = summary.get('trades', 0)
        wins = summary.get('wins', 0)
        losses = summary.get('losses', 0)
        winrate = (wins / trades * 100) if trades > 0 else 0
        pnl = summary.get('pnl', 0)
        balance = summary.get('balance', 0)
        
        emoji = "📈" if pnl >= 0 else "📉"
        
        message = f"""
{emoji} *DAILY SUMMARY*

📊 Trades: `{trades}` (W: {wins}, L: {losses})
📈 Win Rate: `{winrate:.1f}%`
💵 P&L: `${pnl:+.2f}`
💰 Balance: `${balance:.2f}`
"""
        await self.send_message(message)


# Global instance
telegram_notifier = TelegramNotifier()

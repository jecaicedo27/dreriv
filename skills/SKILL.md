---
name: deriv-websocket-trading
description: "Deriv.com WebSocket API v3 integration for synthetic indices trading. Use when building connections to Deriv, subscribing to ticks/candles, executing trades (Rise/Fall, Higher/Lower, Even/Odd), or handling Deriv-specific responses. Covers authentication, tick streaming, OHLC candles, contract purchase, and portfolio management via wss://ws.derivws.com/websockets/v3."
---

# Deriv WebSocket Trading Integration

## Overview

Specialized knowledge for building a persistent WebSocket client that connects to Deriv's synthetic indices API. Covers real-time tick streaming, candle construction, trade execution, and portfolio monitoring for algorithmic trading bots.

## When to Use This Skill

- Connecting to Deriv WebSocket API
- Subscribing to synthetic indices tick streams (R_75, R_100, CRASH1000, etc.)
- Building OHLC candles from tick data
- Executing binary options contracts (Rise/Fall, Higher/Lower, Even/Odd)
- Managing open positions and portfolio queries
- Handling reconnection, heartbeat, and error recovery

## Do Not Use This Skill When

- Working with REST APIs (Deriv uses WebSocket exclusively for real-time data)
- Building for traditional forex brokers (MT4/MT5) — Deriv has its own protocol
- Processing historical data that's already in the database

## Critical Knowledge: Deriv API Specifics

### Connection URL
```
wss://ws.derivws.com/websockets/v3?app_id={APP_ID}
```
- App ID is registered at developers.deriv.com
- One WebSocket connection handles ALL subscriptions
- Keep-alive with `{"ping": 1}` every 30 seconds

### Authentication Flow
```python
# Step 1: Authorize
await ws.send(json.dumps({"authorize": API_TOKEN}))
response = await ws.recv()
# Response contains: loginid, balance, currency, email
# MUST authorize before any other call
```

### Subscribing to Ticks
```python
# Subscribe returns continuous stream until unsubscribed
await ws.send(json.dumps({
    "ticks": "R_75",      # Symbol
    "subscribe": 1         # 1 = subscribe, omit = one-shot
}))
# Each tick response:
# {"tick": {"symbol": "R_75", "epoch": 1707300000, "quote": 450231.50, "id": "abc123"}}
```

### Subscribing to OHLC Candles
```python
await ws.send(json.dumps({
    "ticks_history": "R_75",
    "adjust_start_time": 1,
    "count": 1000,          # Historical candles to fetch first
    "end": "latest",
    "granularity": 60,       # Seconds: 60=1m, 300=5m, 900=15m, 3600=1h
    "style": "candles",
    "subscribe": 1           # Continue receiving new candles
}))
# Initial response: {"candles": [{...}, {...}]}
# Subsequent: {"ohlc": {"open": "...", "high": "...", "low": "...", "close": "...", "epoch": ...}}
```

### Executing a Trade (Buy Contract)
```python
# Rise/Fall (CALL/PUT) contract
await ws.send(json.dumps({
    "buy": 1,
    "subscribe": 1,          # Subscribe to contract updates
    "price": 5.00,           # Stake amount
    "parameters": {
        "contract_type": "CALL",    # CALL=Rise, PUT=Fall
        "symbol": "R_75",
        "duration": 5,
        "duration_unit": "m",        # m=minutes, t=ticks, s=seconds
        "currency": "USD",
        "basis": "stake",
        "amount": 5.00
    }
}))
# Response: {"buy": {"contract_id": 12345, "buy_price": 5.00, "payout": 9.50, ...}}
```

### Contract Types Reference
| Type | contract_type Values | Notes |
|------|---------------------|-------|
| Rise/Fall | CALL, PUT | Predict direction at expiry |
| Higher/Lower | CALL, PUT + barrier | Needs barrier price parameter |
| Even/Odd | DIGITEVEN, DIGITODD | Last digit of price |
| Over/Under | DIGITOVER, DIGITUNDER | Last digit vs threshold |
| Matches/Differs | DIGITMATCH, DIGITDIFF | Last digit = specific number |

### Higher/Lower with Barrier
```python
"parameters": {
    "contract_type": "CALL",
    "symbol": "R_75",
    "duration": 5,
    "duration_unit": "m",
    "currency": "USD",
    "basis": "stake",
    "amount": 5.00,
    "barrier": "+0.50"    # Relative barrier (+ or -) from spot
}
```

### Monitoring Open Contracts
```python
# Get all open positions
await ws.send(json.dumps({"portfolio": 1}))
# Response: {"portfolio": {"contracts": [{"contract_id": ..., "buy_price": ..., "payout": ...}]}}

# Subscribe to a specific contract's updates
await ws.send(json.dumps({
    "proposal_open_contract": 1,
    "contract_id": 12345,
    "subscribe": 1
}))
# Receives real-time P&L updates until contract closes
```

### Account Balance
```python
await ws.send(json.dumps({"balance": 1, "subscribe": 1}))
# Streams balance updates on every trade
```

## Synthetic Indices — What You MUST Know

These are NOT real markets. They are algorithmically generated:

| Index | Symbol | Behavior |
|-------|--------|----------|
| Volatility 25 | R_25 | ~25% annual volatility, smoothest |
| Volatility 50 | R_50 | ~50% annual volatility |
| Volatility 75 | R_75 | ~75% annual volatility, popular |
| Volatility 100 | R_100 | ~100% annual volatility, most volatile |
| Crash 1000 | CRASH1000 | Bearish spikes avg every ~1000 ticks |
| Crash 500 | CRASH500 | Bearish spikes avg every ~500 ticks |
| Boom 1000 | BOOM1000 | Bullish spikes avg every ~1000 ticks |
| Boom 500 | BOOM500 | Bullish spikes avg every ~500 ticks |

**Key implications for code:**
- Available 24/7/365 — no market hours, no weekends off
- No volume data (tick_count is the proxy)
- Spikes in Crash/Boom are sudden 1-3 tick events — detect by % change > 4σ
- Volatility indices mean-revert to their target volatility

## Implementation Pattern: Robust Client

```python
import asyncio
import websockets
import json
from datetime import datetime

class DerivClient:
    """Production-grade Deriv WebSocket client"""
    
    def __init__(self, app_id: str, api_token: str):
        self.url = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
        self.api_token = api_token
        self.ws = None
        self.subscriptions = {}
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._running = False
        
    async def connect(self):
        """Connect with automatic reconnection and exponential backoff"""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 1  # Reset on success
                    
                    # Authenticate
                    await self._authorize()
                    
                    # Resubscribe to all previous subscriptions
                    await self._resubscribe()
                    
                    # Main message loop
                    async for message in ws:
                        await self._handle_message(json.loads(message))
                        
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                if not self._running:
                    break
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
    
    async def _authorize(self):
        await self.ws.send(json.dumps({"authorize": self.api_token}))
        resp = json.loads(await self.ws.recv())
        if "error" in resp:
            raise Exception(f"Auth failed: {resp['error']['message']}")
        return resp
    
    async def subscribe_ticks(self, symbol: str, callback):
        """Subscribe to tick stream for a symbol"""
        msg = {"ticks": symbol, "subscribe": 1}
        await self.ws.send(json.dumps(msg))
        self.subscriptions[f"ticks_{symbol}"] = (msg, callback)
    
    async def subscribe_candles(self, symbol: str, granularity: int, callback):
        """Subscribe to OHLC candle stream"""
        msg = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": 1000,
            "end": "latest", 
            "granularity": granularity,
            "style": "candles",
            "subscribe": 1
        }
        await self.ws.send(json.dumps(msg))
        self.subscriptions[f"candles_{symbol}_{granularity}"] = (msg, callback)
    
    async def buy_contract(self, symbol, contract_type, amount, duration, duration_unit="m", barrier=None):
        """Execute a trade"""
        params = {
            "contract_type": contract_type,
            "symbol": symbol,
            "duration": duration,
            "duration_unit": duration_unit,
            "currency": "USD",
            "basis": "stake",
            "amount": float(amount)
        }
        if barrier is not None:
            params["barrier"] = str(barrier)
            
        msg = {"buy": 1, "subscribe": 1, "price": float(amount), "parameters": params}
        await self.ws.send(json.dumps(msg))
```

## Error Handling Rules

1. **All Deriv errors** have format: `{"error": {"code": "...", "message": "..."}}`
2. **RateLimit errors** (code: `RateLimit`): Back off 60 seconds
3. **InvalidToken** (code: `InvalidToken`): Stop bot, alert user
4. **ContractCreationFailure**: Log and skip, don't retry same trade
5. **MarketIsClosed**: Should never happen with synthetics, but handle gracefully
6. **InsufficientBalance**: Stop trading, alert user immediately

## Safety Checklist

- [ ] Never hardcode API tokens — use environment variables
- [ ] Always validate response has no "error" key before processing
- [ ] Implement circuit breaker: 5+ reconnects in 10 min → pause and alert
- [ ] Log every WebSocket message for debugging (with rotation)
- [ ] Test on demo account FIRST — use `DERIV_ACCOUNT_TYPE=demo`
- [ ] Track latency of each tick (epoch vs received time)

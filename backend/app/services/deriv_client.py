"""
Deriv WebSocket API Client
Based on skill: deriv-websocket-trading

Persistent WebSocket connection to Deriv API v3 with:
- Auto-reconnection
- Heartbeat/ping-pong
- Circuit breaker
- Authentication
- Subscriptions to ticks and candles
"""
import asyncio
import websockets
import json
from typing import Optional, Callable, Dict, Any
from loguru import logger
from datetime import datetime

from app.core.config import get_settings

settings = get_settings()


class DerivWebSocketClient:
    """
    Persistent WebSocket client for Deriv API v3
    """
    
    def __init__(self, app_id: int = None):
        actual_app_id = app_id or settings.DERIV_APP_ID
        self.url = f"wss://ws.derivws.com/websockets/v3?app_id={actual_app_id}"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_authorized = False
        self.running = False
        
        # Callbacks for data handlers
        self.tick_callback: Optional[Callable] = None
        self.candle_callback: Optional[Callable] = None
        self.balance_callback: Optional[Callable] = None
        self.contract_callback: Optional[Callable] = None
        
        # Request handling (Concurrency Fix)
        self.req_id_counter = 1
        self.pending_requests: Dict[int, asyncio.Future] = {}
        
        # Heartbeat
        self.last_ping = None
        self.ping_interval = 30  # seconds
        
        # Circuit breaker
        self.connection_failures = 0
        self.max_failures = 5
        self.backoff_time = 5  # seconds
        
        # Subscriptions tracking
        self.active_subscriptions: Dict[str, str] = {}  # symbol -> subscription_id
        
    async def connect(self):
        """
        Establish WebSocket connection
        """
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            logger.info(f"🔌 Connecting to Deriv WebSocket... (App ID: {settings.DERIV_APP_ID})")
            self.ws = await websockets.connect(
                self.url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10,
                ssl=ssl_context
            )
            self.is_connected = True
            self.connection_failures = 0
            logger.success("✅ Connected to Deriv WebSocket")
            
            # Authorize is now handled by the caller or reconnection logic
            # to avoid deadlock with message_handler_loop
            
            return True
            
        except Exception as e:
            self.connection_failures += 1
            logger.error(f"❌ Connection failed ({self.connection_failures}/{self.max_failures}): {e}")
            
            if self.connection_failures >= self.max_failures:
                logger.critical("🚨 Circuit breaker activated - too many connection failures")
                return False
            
            # Exponential backoff
            backoff = self.backoff_time * (2 ** (self.connection_failures - 1))
            logger.warning(f"⏳ Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            return await self.connect()

    async def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send request and wait for response using Future pattern
        (Fixes concurrency issue)
        """
        if not self.ws or not self.is_connected:
            logger.error("❌ Cannot send - not connected")
            return {}
            
        # Generate req_id
        req_id = self.req_id_counter
        self.req_id_counter += 1
        request['req_id'] = req_id
        
        # Create future
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending_requests[req_id] = future
        
        try:
            await self.ws.send(json.dumps(request))
            logger.debug(f"📤 Sent: {request}")
            
            # Wait for response (handled by message_handler_loop)
            response = await asyncio.wait_for(future, timeout=10.0)
            return response
            
        except asyncio.TimeoutError:
            logger.error(f"❌ Request {req_id} timed out")
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]
            return {}
        except Exception as e:
            logger.error(f"❌ Request error: {e}")
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]
            return {}
    
    async def authorize(self, api_token: str = None):
        """
        Authorize with API token. Uses provided token or falls back to settings.
        """
        try:
            token = api_token or settings.DERIV_API_TOKEN
            request = {
                "authorize": token
            }
            # Use send_request pattern
            response = await self.send_request(request)
            
            if "authorize" in response:
                self.is_authorized = True
                auth_data = response["authorize"]
                balance = auth_data.get("balance", 0)
                currency = auth_data.get("currency", "USD")
                
                # account_type might be in account_list or root depending on token
                account_type = "unknown"
                if "account_list" in auth_data and len(auth_data["account_list"]) > 0:
                    account_type = auth_data["account_list"][0].get("account_type", "unknown")
                elif "account_type" in auth_data:
                    account_type = auth_data["account_type"]
                    
                # Identify account type
                is_virtual = auth_data.get('is_virtual')
                account_type = "DEMO" if is_virtual else "REAL_MONEY"
                
                logger.success(f"✅ Authorized - {account_type} account")
                logger.info(f"💰 Balance: {balance} {currency}")
                return auth_data
            else:
                logger.error(f"❌ Authorization failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Authorization error: {e}")
            return None
            
    async def subscribe_to_ticks(self, symbol: str):
        """
        Subscribe to tick stream for a symbol
        """
        try:
            request = {
                "ticks": symbol,
                "subscribe": 1
            }
            response = await self.send_request(request)
            
            if "subscription" in response:
                sub_id = response["subscription"]["id"]
                self.active_subscriptions[symbol] = sub_id
                logger.success(f"✅ Subscribed to {symbol} ticks (ID: {sub_id})")
                return sub_id
            else:
                logger.error(f"❌ Subscription failed for {symbol}: {response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Subscription error: {e}")
            return None
    
    async def subscribe_to_candles(self, symbol: str, granularity: int = 60):
        """
        Subscribe to OHLC candles. Returns the response containing historical candles.
        """
        try:
            request = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": 1000,
                "end": "latest",
                "granularity": granularity,
                "start": 1,
                "style": "candles",
                "subscribe": 1
            }
            response = await self.send_request(request)
            
            if "candles" in response or "ohlc" in response:
                logger.success(f"✅ Subscribed to {symbol} candles ({granularity}s)")
                return response
            else:
                logger.error(f"❌ Candle subscription failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Candle subscription error: {e}")
            return None
    
    async def buy_contract(
        self,
        symbol: str,
        contract_type: str,
        amount: float,
        duration: int,
        duration_unit: str = "s",
        basis: str = "stake"
    ):
        """
        Execute a trade
        """
        try:
            request = {
                "buy": "1",
                "price": float(amount),
                "subscribe": 1,
                "parameters": {
                    "contract_type": contract_type,
                    "symbol": symbol,
                    "amount": float(amount),
                    "duration": duration,
                    "duration_unit": duration_unit,
                    "basis": basis,
                    "currency": "USD"
                }
            }
            
            # Use send_request pattern - no more manual recv()!
            response = await self.send_request(request)
            
            if "buy" in response:
                contract = response["buy"]
                contract_id = contract["contract_id"]
                buy_price = contract["buy_price"]
                logger.success(f"✅ Trade executed - Contract ID: {contract_id}, Price: {buy_price}")
                return contract
            else:
                logger.error(f"❌ Trade failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            return None

    async def buy_accumulator(
        self,
        symbol: str,
        amount: float,
        growth_rate: float = 0.02,
        take_profit: float = None
    ):
        """
        Buy an Accumulator (ACCU) contract.
        No duration needed - contract stays open until barrier is hit or sold.
        
        Args:
            symbol: e.g. 'BOOM1000'
            amount: Stake in USD
            growth_rate: 0.01 to 0.05 (1% to 5%)
            take_profit: Optional take profit amount in USD
        """
        try:
            params = {
                "contract_type": "ACCU",
                "symbol": symbol,
                "amount": float(amount),
                "growth_rate": growth_rate,
                "basis": "stake",
                "currency": "USD"
            }

            if take_profit:
                params["limit_order"] = {
                    "take_profit": float(take_profit)
                }

            request = {
                "buy": "1",
                "price": float(amount),
                "subscribe": 1,
                "parameters": params
            }

            logger.info(f"🎰 Buying ACCU: {symbol} ${amount} @ {growth_rate*100}% growth"
                        f"{f' TP=${take_profit}' if take_profit else ''}")

            response = await self.send_request(request)

            if "buy" in response:
                contract = response["buy"]
                contract_id = contract["contract_id"]
                buy_price = contract["buy_price"]
                logger.success(f"✅ ACCU Contract opened - ID: {contract_id}, Price: {buy_price}")
                return contract
            else:
                error_msg = response.get('error', {}).get('message', str(response))
                logger.error(f"❌ ACCU buy failed: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"❌ ACCU buy error: {e}")
            return None

    async def sell_contract(self, contract_id: int, price: float = 0):
        """
        Sell/close an open contract early.
        
        Args:
            contract_id: The contract to sell
            price: Minimum acceptable sell price (0 = sell at market)
        """
        try:
            request = {
                "sell": int(contract_id),
                "price": float(price)
            }

            response = await self.send_request(request)

            if "sell" in response:
                sell_data = response["sell"]
                sold_for = sell_data.get("sold_for", 0)
                logger.success(f"✅ Contract {contract_id} sold for ${sold_for}")
                return sell_data
            else:
                error_msg = response.get('error', {}).get('message', str(response))
                logger.error(f"❌ Sell failed: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"❌ Sell error: {e}")
            return None

    async def get_portfolio(self):
        """Get all open contracts (portfolio)"""
        try:
            response = await self.send_request({"portfolio": 1, "contract_type": ["ACCU"]})
            if "portfolio" in response:
                return response["portfolio"].get("contracts", [])
            return []
        except Exception as e:
            logger.error(f"❌ Portfolio error: {e}")
            return []

    async def get_contract_status(self, contract_id: int):
        """
        Get current status of a contract
        """
        try:
            request = {
                "proposal_open_contract": 1,
                "contract_id": int(contract_id)
            }
            
            # Use send_request pattern
            response = await self.send_request(request)
            
            if "proposal_open_contract" in response:
                return response["proposal_open_contract"]
            else:
                logger.error(f"❌ Failed to get contract status: {response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Get contract status error: {e}")
            return None
    
    async def heartbeat_loop(self):
        """
        Send periodic pings
        """
        while self.running:
            try:
                if self.is_connected and self.ws:
                    # Ping doesn't strictly need req_id handling if we don't care about the pong response payload
                    # But better to use send_request to keep it clean
                    await self.send_request({"ping": 1})
                    self.last_ping = datetime.now()
                
                await asyncio.sleep(self.ping_interval)
                
            except Exception as e:
                logger.error(f"❌ Heartbeat error: {e}")
                await asyncio.sleep(5)

    async def message_handler_loop(self):
        """
        Main loop to handle ALL incoming messages.
        IMPORTANT: This is the ONLY place that calls recv().
        During reconnection, authorize() and subscribe_to_ticks() 
        use send_request() which creates futures resolved by THIS loop's recv().
        So we must NOT have two recv() calls active simultaneously.
        """
        while self.running:
            try:
                if not self.is_connected or not self.ws:
                    # Reconnect
                    logger.warning("🔄 Connection lost, attempting to reconnect...")
                    if await self.connect():
                        # Start recv() loop FIRST, then auth/subscribe will work
                        # because send_request creates futures resolved by recv()
                        # We use asyncio.ensure_future so they run in the SAME event loop
                        # and recv() below will pick up their responses
                        
                        # Auth inline — send the raw request and handle response in recv() below
                        token = settings.DERIV_API_TOKEN
                        auth_req_id = self.req_id_counter
                        self.req_id_counter += 1
                        loop = asyncio.get_event_loop()
                        auth_future = loop.create_future()
                        self.pending_requests[auth_req_id] = auth_future
                        await self.ws.send(json.dumps({
                            "authorize": token,
                            "req_id": auth_req_id
                        }))
                        
                        # Now recv() the auth response
                        try:
                            auth_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
                            auth_data = json.loads(auth_msg)
                            auth_rid = auth_data.get('req_id')
                            if auth_rid and auth_rid in self.pending_requests:
                                f = self.pending_requests.pop(auth_rid)
                                if not f.done():
                                    f.set_result(auth_data)
                            
                            if "authorize" in auth_data:
                                self.is_authorized = True
                                is_virtual = auth_data["authorize"].get("is_virtual")
                                balance = auth_data["authorize"].get("balance", 0)
                                acct = "DEMO" if is_virtual else "REAL"
                                logger.success(f"✅ Reconnected & authorized - {acct} | Balance: {balance}")
                            else:
                                logger.error(f"❌ Re-auth failed: {auth_data}")
                        except Exception as auth_err:
                            logger.error(f"❌ Re-auth recv error: {auth_err}")
                            self.is_connected = False
                            await asyncio.sleep(3)
                            continue
                        
                        # Re-subscribe to ticks (same inline pattern)
                        for symbol in list(self.active_subscriptions.keys()):
                            try:
                                sub_req_id = self.req_id_counter
                                self.req_id_counter += 1
                                sub_future = loop.create_future()
                                self.pending_requests[sub_req_id] = sub_future
                                await self.ws.send(json.dumps({
                                    "ticks": symbol,
                                    "subscribe": 1,
                                    "req_id": sub_req_id
                                }))
                                
                                sub_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
                                sub_data = json.loads(sub_msg)
                                sub_rid = sub_data.get('req_id')
                                if sub_rid and sub_rid in self.pending_requests:
                                    f = self.pending_requests.pop(sub_rid)
                                    if not f.done():
                                        f.set_result(sub_data)
                                
                                if "subscription" in sub_data:
                                    self.active_subscriptions[symbol] = sub_data["subscription"]["id"]
                                    logger.success(f"✅ Re-subscribed to {symbol}")
                            except Exception as sub_err:
                                logger.error(f"❌ Re-subscribe {symbol} error: {sub_err}")
                        
                        logger.info("🔄 Reconnection complete, resuming message loop")
                        continue
                    else:
                        await asyncio.sleep(5)
                        continue
                
                # The ONLY place calling recv() during normal operation
                message = await self.ws.recv()
                data = json.loads(message)
                
                # 1. Check if it's a response to a pending request
                req_id = data.get('req_id')
                if req_id and req_id in self.pending_requests:
                    future = self.pending_requests.pop(req_id)
                    if not future.done():
                        future.set_result(data)
                
                # 2. Handle data streams
                if "tick" in data:
                    await self.handle_tick(data["tick"])
                
                elif "ohlc" in data or "candles" in data:
                    await self.handle_candle(data.get("ohlc") or data.get("candles"))
                
                elif "balance" in data:
                    await self.handle_balance(data["balance"])
                
                elif "proposal_open_contract" in data:
                    await self.handle_contract_update(data["proposal_open_contract"]) 

                elif "error" in data:
                    logger.error(f"🚨 Deriv API Error: {data['error']}")
                
            except websockets.ConnectionClosed:
                logger.warning("⚠️ WebSocket connection closed")
                self.is_connected = False
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"❌ Message handler error: {e}")
                self.is_connected = False
                try:
                    if self.ws:
                        await self.ws.close()
                except Exception:
                    pass
                self.ws = None
                await asyncio.sleep(2)

    async def start(self):
        """
        Start the WebSocket client
        """
        self.running = True
        logger.info("🚀 Starting Deriv WebSocket client...")
        
        # Connect
        if not await self.connect():
            logger.critical("❌ Failed to establish connection - aborting")
            return
        
        # Start background tasks
        # IMPORTANT: Start handler BEFORE authorizing so futures can be resolved
        handler_task = asyncio.create_task(self.message_handler_loop())
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        
        # Now authorize
        await self.authorize()
        
        # Wait for tasks
        await asyncio.gather(heartbeat_task, handler_task)
    
    async def stop(self):
        """
        Gracefully stop the client
        """
        logger.warning("⏸️ Stopping Deriv WebSocket client...")
        self.running = False
        
        if self.ws:
            await self.ws.close()
        
        logger.success("✅ Deriv WebSocket client stopped")
    
    def set_tick_callback(self, callback: Callable):
        """Set callback function for tick data"""
        self.tick_callback = callback
    
    def set_candle_callback(self, callback: Callable):
        """Set callback function for candle data"""
        self.candle_callback = callback

    def set_balance_callback(self, callback: Callable):
        """Set callback function for balance updates"""
        self.balance_callback = callback

    def set_contract_callback(self, callback: Callable):
        """Set callback function for contract updates"""
        self.contract_callback = callback

    async def subscribe_balance(self):
        """
        Subscribe to account balance updates
        """
        try:
            request = {
                "balance": 1,
                "subscribe": 1
            }
            # Balance subscription usually returns immediate response + stream
            response = await self.send_request(request)
            
            if "balance" in response:
                logger.success(f"✅ Subscribed to balance updates")
                return True
            else:
                logger.error(f"❌ Balance subscription failed: {response}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Balance subscription error: {e}")
            return False

    async def handle_balance(self, balance_data: Dict[str, Any]):
        """
        Process incoming balance update
        """
        logger.info(f"💰 Balance Update: {balance_data.get('balance')} {balance_data.get('currency')}")
        
        # Call custom callback if set
        if self.balance_callback:
            await self.balance_callback(balance_data)

    async def handle_contract_update(self, contract_data: Dict[str, Any]):
        """
        Process incoming contract update (proposal_open_contract)
        """
        contract_id = contract_data.get('contract_id')
        status = contract_data.get('status')
        
        logger.debug(f"📜 Contract Update: {contract_id} - Status: {status}")
        
        # Call custom callback if set
        if self.contract_callback:
            await self.contract_callback(contract_data)

    async def handle_tick(self, tick_data: Dict[str, Any]):
        """
        Process incoming tick data
        """
        # Call custom callback if set
        if self.tick_callback:
            await self.tick_callback(tick_data)

    async def handle_candle(self, candle_data: Dict[str, Any]):
        """
        Process incoming candle data
        """
        # Call custom callback if set
        if self.candle_callback:
            await self.candle_callback(candle_data)


# Global client instance
deriv_client = DerivWebSocketClient()

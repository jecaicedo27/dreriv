import asyncio
import json
import ssl
import websockets

async def main():
    url = "wss://ws.derivws.com/websockets/v3?app_id=125728"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    async with websockets.connect(url, ssl=ctx) as ws:
        await ws.send(json.dumps({"authorize": "WTgzA8BOfL7OLUK"}))
        print(await ws.recv())
        
        await ws.send(json.dumps({
            "proposal_open_contract": 1,
            "contract_id": 306393110528
        }))
        res = await ws.recv()
        print(f"RES: {res}")

asyncio.run(main())

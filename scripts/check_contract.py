
import asyncio
import os
import json
import ssl
import websockets
from dotenv import load_dotenv

load_dotenv("/var/www/jhonk/dreriv/.env")

API_TOKEN = os.getenv("DERIV_API_TOKEN")
APP_ID = os.getenv("DERIV_APP_ID")

async def check_contract(contract_id):
    url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    async with websockets.connect(url, ssl=ctx) as ws:
        # Auth
        await ws.send(json.dumps({"authorize": API_TOKEN}))
        auth = await ws.recv()
        print(f"Auth: {auth}")
        
        # Check Contract
        req = {
            "proposal_open_contract": 1,
            "contract_id": contract_id
        }
        await ws.send(json.dumps(req))
        res = await ws.recv()
        print(f"Contract Status: {res}")

if __name__ == "__main__":
    # Test with one of the stale contract IDs
    asyncio.run(check_contract(306393110528))

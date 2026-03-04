"""
Standalone FastAPI application for the Forex (EUR/USD) Bot.
Runs in its own Docker container, independent of the R_100 bot.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from loguru import logger
import os
import asyncio

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌍 Starting Forex Bot (EUR/USD) — standalone container")

    # Start forex bot
    from app.forex_bot import start_forex_bot
    asyncio.create_task(start_forex_bot())

    logger.success("✅ Forex Bot started successfully")
    yield
    logger.warning("⏸️  Shutting down Forex Bot...")


app = FastAPI(
    title="Deriv Forex Bot — EUR/USD",
    version="2.0.0",
    lifespan=lifespan,
    root_path="/deriv",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/forex")
async def serve_forex_dashboard():
    forex_path = os.path.join(static_dir, "forex_dashboard.html")
    if os.path.exists(forex_path):
        return FileResponse(forex_path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0"
        })
    return {"error": "Forex dashboard not found"}


@app.get("/forex-simulations")
async def serve_forex_simulations():
    path = os.path.join(static_dir, "forex_simulations.html")
    if os.path.exists(path):
        return FileResponse(path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0"
        })
    return {"error": "Forex simulations page not found"}


@app.get("/health")
async def health_check():
    from app.forex_bot import _forex_running
    return {
        "status": "healthy",
        "app": "Deriv Forex Bot",
        "version": "2.0.0",
        "forex_running": _forex_running,
    }


# ── API Router ──────────────────────────────────────────────────────────────

from app.api import forex_api
app.include_router(forex_api.router, tags=["forex"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main_forex:app", host="0.0.0.0", port=8000, reload=True)

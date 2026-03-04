"""
Main FastAPI application for Deriv Trading Bot V2
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from loguru import logger
import os

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.database import engine, Base
from app.bot import TradingBot
import asyncio

# Initialize settings and logging
settings = get_settings()
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown events
    """
    # Startup
    logger.info(f"🚀 Starting {settings.APP_NAME}")
    logger.info(f"📊 Database: {settings.DB_NAME}")
    logger.info(f"🎯 Deriv Account: {settings.DERIV_ACCOUNT_TYPE.upper()}")
    logger.info(f"🤖 Groq Layer 2 Enabled: {settings.USE_GROQ_LAYER2}")
    logger.info(f"🔍 pgvector Enabled: {settings.ENABLE_PGVECTOR}")
    
    # Initialize Rise/Fall bot
    bot = TradingBot()
    app.state.bot = bot
    logger.info("🎬 Spawning Rise/Fall (R_100) bot background task...")
    asyncio.create_task(bot.start())

    logger.success("✅ Application started successfully")

    yield

    # Shutdown
    logger.warning("⏸️  Shutting down application...")
    if hasattr(app.state, "bot"):
        await app.state.bot.stop()
    logger.success("✅ Application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Automated trading bot for Deriv.com synthetic indices with 3-layer AI architecture",
    version="2.0.0",
    lifespan=lifespan,
    root_path="/deriv"  # For Nginx reverse proxy
)

# CORS middleware (for dashboard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ============================================
# ROUTES
# ============================================

@app.get("/dashboard")
async def serve_dashboard():
    """Serve the dashboard HTML"""
    dashboard_path = os.path.join(static_dir, "dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(
            dashboard_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"error": "Dashboard not found", "path": dashboard_path}

@app.get("/simulations")
async def serve_simulations():
    """Serve the simulations/fractal lab page"""
    sim_path = os.path.join(static_dir, "simulations.html")
    if os.path.exists(sim_path):
        return FileResponse(
            sim_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"error": "Simulations page not found", "path": sim_path}

@app.get("/accumulators")
async def serve_accumulators():
    """Serve the Accumulators bot dashboard"""
    accu_path = os.path.join(static_dir, "accumulators.html")
    if os.path.exists(accu_path):
        return FileResponse(accu_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return {"error": "Accumulators page not found"}




@app.get("/health")
async def health_check():
    """
    Health check endpoint for Docker healthcheck
    """
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": "2.0.0",
        "account_type": settings.DERIV_ACCOUNT_TYPE
    }


@app.get("/")
async def root():
    """
    Root endpoint
    """
    return {
        "app": settings.APP_NAME,
        "version": "2.0.0",
        "message": "Deriv Trading Bot V2 API",
        "docs": "/docs",
        "health": "/health",
        "dashboard": "/dashboard"
    }


# ============================================
# API ROUTERS
# ============================================

from app.api import bot_status
from app.api import analysis_metrics
from app.api import simulation_api
from app.api import accu_status
from app.api import decision_tracker_api
app.include_router(bot_status.router, prefix="/api", tags=["bot"])
app.include_router(analysis_metrics.router, prefix="/api", tags=["analysis"])
app.include_router(simulation_api.router, prefix="/api", tags=["simulation"])
app.include_router(accu_status.router, prefix="/api", tags=["accumulator"])
app.include_router(decision_tracker_api.router, prefix="/api", tags=["tracker"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

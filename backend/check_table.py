
from sqlalchemy import create_engine, text
from app.core.config import get_settings

try:
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.connect() as conn:
        # Check if table exists using PostgreSQL specific function
        result = conn.execute(text("SELECT to_regclass('public.simulation_runs');"))
        exists = result.fetchone()[0] is not None
        print(f"Table simulation_runs exists: {exists}")
except Exception as e:
    print(f"Error checking table: {e}")

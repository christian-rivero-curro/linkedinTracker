import os
from functools import lru_cache
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()


@lru_cache(maxsize=1)
def get_engine():
    db_url = os.environ.get("SUPABASE_DB_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
    return create_engine(db_url, pool_pre_ping=True, pool_size=3, max_overflow=2)

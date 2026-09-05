import os
from functools import lru_cache
from sqlalchemy import create_engine


@lru_cache(maxsize=1)
def get_engine():
    db_url = os.environ["SUPABASE_DB_URL"]
    return create_engine(db_url, pool_pre_ping=True, pool_size=3, max_overflow=2)

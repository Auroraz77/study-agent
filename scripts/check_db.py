import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import engine


if __name__ == "__main__":
    with engine.connect() as connection:
        version = connection.execute(text("select version()")).scalar_one()
        vector = connection.execute(
            text("select exists(select 1 from pg_extension where extname = 'vector')")
        ).scalar_one()
    print(version)
    print(f"pgvector installed: {vector}")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.db.database_url import normalize_database_url

engine = create_engine(
    normalize_database_url(settings.database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_database_connection() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return "ok"

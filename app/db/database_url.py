def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 for PostgreSQL URLs that omit a SQLAlchemy driver."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url

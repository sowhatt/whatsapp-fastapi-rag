from app.db.database_url import normalize_database_url


def test_railway_postgresql_url_uses_psycopg_3_driver():
    assert normalize_database_url(
        "postgresql://user:secret@postgres.railway.internal:5432/railway"
    ) == "postgresql+psycopg://user:secret@postgres.railway.internal:5432/railway"


def test_legacy_postgres_url_uses_psycopg_3_driver():
    assert normalize_database_url(
        "postgres://user:secret@postgres.railway.internal:5432/railway"
    ) == "postgresql+psycopg://user:secret@postgres.railway.internal:5432/railway"


def test_explicit_driver_and_sqlite_urls_are_unchanged():
    assert normalize_database_url("postgresql+psycopg://host/db") == (
        "postgresql+psycopg://host/db"
    )
    assert normalize_database_url("sqlite://") == "sqlite://"

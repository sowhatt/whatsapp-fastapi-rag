from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.schema_audit import audit_online_schema


def test_schema_audit_is_ready_when_expected_models_exist():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        result = audit_online_schema(db=db)
    finally:
        db.close()

    assert result["read_only"] is True
    assert result["ready"] is True
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["missing_indexes"] == {}


def test_schema_audit_reports_missing_tables_without_modifying_database():
    engine = create_engine("sqlite://")
    db = sessionmaker(bind=engine)()
    try:
        result = audit_online_schema(db=db)
    finally:
        db.close()

    assert result["read_only"] is True
    assert result["ready"] is False
    assert "online_stores" in result["missing_tables"]
    assert "online_orders" in result["missing_tables"]
    assert "stock_reservations" in result["missing_tables"]
    assert "outbox_events" in result["missing_tables"]

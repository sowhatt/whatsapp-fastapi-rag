from pathlib import Path

from app.db.session import SessionLocal


SQL_FILES = [
    "app/analytics/sql/bi_01_materialized_views.sql",
    "app/analytics/sql/bi_01_financial_position.sql",
    "app/analytics/sql/bi_01_inventory_history.sql",
]


def install_analytics() -> None:
    db = SessionLocal()

    try:
        connection = db.connection()
        raw = connection.connection
        cursor = raw.cursor()

        try:
            for filename in SQL_FILES:
                path = Path(filename)

                if not path.exists():
                    raise FileNotFoundError(
                        f"Fichier analytique absent : {filename}"
                    )

                print(f"Installation : {filename}")

                cursor.execute(
                    path.read_text(encoding="utf-8")
                )

        finally:
            cursor.close()

        raw.commit()

        print(
            "✅ Materialized Views BI-01 installées."
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    install_analytics()

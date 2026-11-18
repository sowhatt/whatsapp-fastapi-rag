"""Existing pilot only: validate schema read-only, never run the historical bootstrap."""
from sqlalchemy import inspect, text
from app.main import app, ensure_catalog_schema
from app.db.session import engine
from app.services.pilot_auth_service import selected_merchant

CORE = frozenset({'merchants','merchant_users','user_phones','user_shop_memberships','shops'})
AUTH = frozenset({'merchant_auth_schema_versions','merchant_auth_devices','merchant_auth_sessions',
    'merchant_auth_attempts','merchant_pin_credentials','merchant_passkey_users','merchant_passkeys',
    'merchant_passkey_challenges','merchant_passkey_rate_limits'})


def validate_existing_schema(database=engine):
    # No Base.metadata.create_all, migrations, seed or historical UPDATE on this path.
    with database.connect() as connection:
        connection.execute(text('BEGIN READ ONLY'))
        try:
            connection.execute(text("SET LOCAL statement_timeout='10s'"))
            schema = inspect(connection)
            tables = set(schema.get_table_names())
            if not CORE <= tables:
                raise RuntimeError('Existing pilot Core schema required; bootstrap is forbidden')
            if selected_merchant() is not None:
                if not AUTH <= tables:
                    raise RuntimeError('Pilot Auth migration required before activation')
                receipt = connection.scalar(text("SELECT count(*) FROM merchant_auth_schema_versions WHERE version='005_pilot_quick_login'"))
                if receipt != 1:
                    raise RuntimeError('Pilot Auth migration receipt missing')
                for table, columns in {
                    'merchant_auth_devices': {'public_key','shop_id','origin'},
                    'merchant_auth_sessions': {'challenge'},
                    'merchant_passkeys': {'shop_id'},
                }.items():
                    if not columns <= {c['name'] for c in schema.get_columns(table)}:
                        raise RuntimeError('Pilot Auth migration incomplete')
        finally:
            connection.rollback()


# RC1 replaced the historical bootstrap with a read-only compatibility check.
# Keep that check and the existing Auth validation on the corrected entry point.
app.router.on_startup.append(validate_existing_schema)

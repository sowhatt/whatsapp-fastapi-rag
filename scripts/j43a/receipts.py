"""Lab proof of atomic local receipts, NOT a Core command implementation."""
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

class IdempotencyConflict(ValueError):
    pass


def apply_command(connection, *, merchant_id, source, key, command_type, fingerprint, effect):
    if connection.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("Caller must own an explicit transaction")
    # A savepoint also protects callers that catch an effect failure and commit.
    with connection.transaction():
        inserted = connection.execute(
            "INSERT INTO command_receipts (merchant_id,source,idempotency_key,command_type,payload_hash,result) "
            "VALUES (%s,%s,%s,%s,%s,'{}') ON CONFLICT DO NOTHING RETURNING idempotency_key",
            (merchant_id,source,key,command_type,fingerprint)).fetchone()
        if not inserted:
            row = connection.execute(
                "SELECT command_type,payload_hash,result FROM command_receipts WHERE merchant_id=%s AND source=%s AND idempotency_key=%s",
                (merchant_id,source,key)).fetchone()
            if row is None or row[:2] != (command_type,fingerprint):
                raise IdempotencyConflict("idempotency key reused with different payload or command")
            return row[2]
        result = effect(connection)
        connection.execute("UPDATE command_receipts SET result=%s WHERE merchant_id=%s AND source=%s AND idempotency_key=%s",
                           (Jsonb(result),merchant_id,source,key))
        return result


def apply_event(connection, *, merchant_id, consumer, event_id, fingerprint, effect):
    if connection.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("Caller must own an explicit transaction")
    with connection.transaction():
        inserted = connection.execute(
            "INSERT INTO inbox_receipts (merchant_id,consumer,event_id,payload_hash) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING event_id", (merchant_id,consumer,event_id,fingerprint)).fetchone()
        if not inserted:
            old = connection.execute("SELECT payload_hash FROM inbox_receipts WHERE merchant_id=%s AND consumer=%s AND event_id=%s",
                                     (merchant_id,consumer,event_id)).fetchone()
            if old is None or old[0] != fingerprint:
                raise IdempotencyConflict("event identity reused with different payload")
            return False
        effect(connection)
        return True

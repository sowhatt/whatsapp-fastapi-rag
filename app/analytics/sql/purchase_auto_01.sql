ALTER TABLE purchases
ADD COLUMN IF NOT EXISTS due_date DATE;

CREATE INDEX IF NOT EXISTS
    ix_purchases_merchant_due_date
ON purchases (
    merchant_id,
    due_date
)
WHERE remaining_amount > 0;

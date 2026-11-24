-- Lot 2: prepared only. Review and apply separately; never run by this sprint.
-- Additive schema; no pilot data changes and no backfill.
BEGIN;
CREATE TABLE sale_photo_drafts (
	id VARCHAR(36) NOT NULL, 
	merchant_id INTEGER NOT NULL, 
	shop_id INTEGER NOT NULL, 
	user_id INTEGER, 
	session_hash VARCHAR(64) NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	extracted JSON NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	confirmed_at TIMESTAMP WITHOUT TIME ZONE, 
	confirmation_hash VARCHAR(64), 
	response JSON, 
	audit JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_sale_photo_draft_receipt_complete CHECK ((confirmed_at IS NULL AND confirmation_hash IS NULL AND response IS NULL AND audit IS NULL) OR (confirmed_at IS NOT NULL AND confirmation_hash IS NOT NULL AND response IS NOT NULL AND audit IS NOT NULL)), 
	FOREIGN KEY(merchant_id) REFERENCES merchants (id), 
	FOREIGN KEY(shop_id) REFERENCES shops (id), 
	FOREIGN KEY(user_id) REFERENCES merchant_users (id)
);
CREATE INDEX ix_sale_photo_drafts_merchant_id ON sale_photo_drafts (merchant_id);
CREATE INDEX ix_sale_photo_drafts_shop_id ON sale_photo_drafts (shop_id);
COMMIT;

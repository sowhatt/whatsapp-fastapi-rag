-- Pilot compatibility port of 6b9dc03. One additive transaction on existing Core.
-- No bootstrap, accounts, security review tables or business DML.
BEGIN;
SELECT pg_advisory_xact_lock(574282601113);
CREATE TABLE IF NOT EXISTS merchant_auth_schema_versions (version VARCHAR(50) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());
-- The alternative 005 used different tables/protocols. Never merge it implicitly.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM merchant_auth_schema_versions WHERE version = '005_pin_device_proof')
       OR to_regclass('merchant_pin_device_keys') IS NOT NULL
       OR to_regclass('merchant_pin_challenges') IS NOT NULL THEN
        RAISE EXCEPTION 'Conflicting PIN migration 005_pin_device_proof: explicit reconciliation required';
    END IF;
END;
$$;
-- S1.5: auth tables only. Apply manually to the intended PostgreSQL database.




CREATE TABLE IF NOT EXISTS merchant_auth_devices (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	device_id VARCHAR(128) NOT NULL,
	device_name VARCHAR(150),
	device_secret_hash VARCHAR(255) NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_used_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_auth_device_identity UNIQUE (id, merchant_id, user_id),
	CONSTRAINT uq_merchant_auth_device UNIQUE (merchant_id, user_id, device_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(user_id) REFERENCES merchant_users (id)
);

CREATE INDEX IF NOT EXISTS ix_merchant_auth_devices_merchant_id ON merchant_auth_devices (merchant_id);

CREATE INDEX IF NOT EXISTS ix_merchant_auth_devices_user_id ON merchant_auth_devices (user_id);

CREATE TABLE IF NOT EXISTS merchant_pin_credentials (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	device_id INTEGER NOT NULL,
	pin_hash VARCHAR(255) NOT NULL,
	failed_attempts INTEGER DEFAULT '0' NOT NULL,
	locked_until TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_pin_device_identity FOREIGN KEY(device_id, merchant_id, user_id) REFERENCES merchant_auth_devices (id, merchant_id, user_id),
	CONSTRAINT uq_merchant_pin_device UNIQUE (device_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(user_id) REFERENCES merchant_users (id)
);

CREATE INDEX IF NOT EXISTS ix_merchant_pin_credentials_merchant_id ON merchant_pin_credentials (merchant_id);

CREATE INDEX IF NOT EXISTS ix_merchant_pin_credentials_user_id ON merchant_pin_credentials (user_id);

CREATE TABLE IF NOT EXISTS merchant_auth_sessions (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	device_id INTEGER NOT NULL,
	purpose VARCHAR(30) DEFAULT 'enrollment' NOT NULL,
	shop_id INTEGER,
	session_token_hash VARCHAR(255) NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_used_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT fk_session_device_identity FOREIGN KEY(device_id, merchant_id, user_id) REFERENCES merchant_auth_devices (id, merchant_id, user_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(user_id) REFERENCES merchant_users (id),
	FOREIGN KEY(shop_id) REFERENCES shops (id),
	UNIQUE (session_token_hash)
);

CREATE INDEX IF NOT EXISTS ix_merchant_auth_sessions_device_id ON merchant_auth_sessions (device_id);

CREATE INDEX IF NOT EXISTS ix_merchant_auth_sessions_merchant_id ON merchant_auth_sessions (merchant_id);

CREATE INDEX IF NOT EXISTS ix_merchant_auth_sessions_user_id ON merchant_auth_sessions (user_id);

CREATE TABLE IF NOT EXISTS merchant_auth_attempts (
	merchant_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	purpose VARCHAR(20) NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	window_started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (merchant_id, user_id, purpose),
	CONSTRAINT ck_auth_attempts_positive CHECK (attempts >= 0),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(user_id) REFERENCES merchant_users (id)
);

-- Upgrade the three S1 prototype tables without touching business tables.

-- Existing prototype sessions have no trustworthy reauthentication provenance.
ALTER TABLE merchant_auth_sessions ADD COLUMN IF NOT EXISTS purpose VARCHAR(30) NOT NULL DEFAULT 'legacy';

ALTER TABLE merchant_auth_sessions ALTER COLUMN purpose SET DEFAULT 'enrollment';

ALTER TABLE merchant_auth_sessions ADD COLUMN IF NOT EXISTS shop_id INTEGER REFERENCES shops(id);

INSERT INTO merchant_auth_schema_versions(version) VALUES ('001_s1_5_pin_enrollment') ON CONFLICT DO NOTHING;



-- S1.6 retained schema, after the S1.5 definitions above. Auth tables only.


CREATE TABLE IF NOT EXISTS merchant_passkey_users (
	user_id INTEGER NOT NULL,
	merchant_id INTEGER NOT NULL,
	user_handle BYTEA NOT NULL,
	PRIMARY KEY (user_id),
	CONSTRAINT uq_passkey_user_identity UNIQUE (user_id, merchant_id),
	FOREIGN KEY(user_id) REFERENCES merchant_users (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	UNIQUE (user_handle)
);

CREATE TABLE IF NOT EXISTS merchant_passkeys (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	credential_id BYTEA NOT NULL,
	public_key BYTEA NOT NULL,
	rp_id VARCHAR(253) NOT NULL,
	sign_count BIGINT NOT NULL,
	backup_eligible BOOLEAN NOT NULL,
	backed_up BOOLEAN NOT NULL,
	name VARCHAR(150) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_used_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT fk_passkey_user_identity FOREIGN KEY(user_id, merchant_id) REFERENCES merchant_passkey_users (user_id, merchant_id),
	CONSTRAINT ck_passkey_counter CHECK (sign_count >= 0 AND sign_count <= 4294967295),
	UNIQUE (credential_id)
);

CREATE INDEX IF NOT EXISTS ix_merchant_passkeys_merchant_id ON merchant_passkeys (merchant_id);

CREATE INDEX IF NOT EXISTS ix_merchant_passkeys_user_id ON merchant_passkeys (user_id);

CREATE TABLE IF NOT EXISTS merchant_passkey_challenges (
	id VARCHAR(64) NOT NULL,
	challenge BYTEA NOT NULL,
	binding_hash VARCHAR(64) NOT NULL,
	purpose VARCHAR(20) NOT NULL,
	merchant_id INTEGER,
	user_id INTEGER,
	shop_id INTEGER,
	name VARCHAR(150),
	rp_id VARCHAR(253) NOT NULL,
	origin VARCHAR(300) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	consumed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT fk_passkey_challenge_user FOREIGN KEY(user_id, merchant_id) REFERENCES merchant_passkey_users (user_id, merchant_id),
	CONSTRAINT ck_passkey_challenge_identity CHECK ((purpose = 'register' AND merchant_id IS NOT NULL AND user_id IS NOT NULL) OR (purpose = 'authenticate' AND merchant_id IS NULL AND user_id IS NULL)),
	FOREIGN KEY(shop_id) REFERENCES shops (id)
);

CREATE INDEX IF NOT EXISTS ix_merchant_passkey_challenges_expires_at ON merchant_passkey_challenges (expires_at);

CREATE INDEX IF NOT EXISTS ix_merchant_passkey_challenges_user_id ON merchant_passkey_challenges (user_id);

CREATE TABLE IF NOT EXISTS merchant_passkey_rate_limits (
	bucket VARCHAR(64) NOT NULL,
	attempts INTEGER NOT NULL,
	window_started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (bucket)
);

INSERT INTO merchant_auth_schema_versions(version) VALUES ('002_s1_6_webauthn') ON CONFLICT DO NOTHING;



ALTER TABLE merchant_auth_devices ADD COLUMN IF NOT EXISTS public_key BYTEA;
ALTER TABLE merchant_auth_devices ADD COLUMN IF NOT EXISTS shop_id INTEGER REFERENCES shops(id);
-- NULL for unproved prototype devices: a fresh enrollment is required, never promotion.
ALTER TABLE merchant_auth_devices ADD COLUMN IF NOT EXISTS origin VARCHAR(300);
ALTER TABLE merchant_auth_sessions ADD COLUMN IF NOT EXISTS challenge BYTEA;
ALTER TABLE merchant_passkeys ADD COLUMN IF NOT EXISTS shop_id INTEGER REFERENCES shops(id);
INSERT INTO merchant_auth_schema_versions(version) VALUES ('005_pilot_quick_login') ON CONFLICT DO NOTHING;
COMMIT;

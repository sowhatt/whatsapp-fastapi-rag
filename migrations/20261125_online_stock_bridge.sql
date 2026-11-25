-- PREPARE UNIQUEMENT. Non appliqué. À relire puis appliquer sur la base de staging
-- AVANT de déployer la branche integration/online-on-shop sur whatzabi-online-staging.
--
-- Ajoute les 6 colonnes du pont de stock Online -> Shop. Additif, idempotent, sans
-- réécriture de données existantes (valeurs par défaut = comportement actuel).
-- Ces mêmes instructions sont aussi exécutées au démarrage d'Online (installeur
-- ONLINE_SCHEMA_SQL) : ce fichier permet de les relire et de les appliquer à l'avance.
-- Prérequis : les tables online_stores, online_product_publications et shops existent.
BEGIN;

-- Boutique du Shop qui prépare les commandes en ligne (NULL = automatique si une seule).
ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS fulfilment_shop_id INTEGER NULL REFERENCES shops(id);
-- Unités gardées pour la caisse (0 = tout le stock est vendable en ligne).
ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS stock_buffer INTEGER NOT NULL DEFAULT 0;
-- Seuil « Dernières unités » (la commande est alors confirmée par le commerçant).
ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER NOT NULL DEFAULT 2;

-- Surcharge du tampon par produit (NULL = valeur de la boutique).
ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS stock_buffer_override INTEGER NULL;
-- Mode de stock : tracked (suivi), daily (quantité du jour), unlimited (sur commande).
ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS stock_mode VARCHAR(20) NOT NULL DEFAULT 'tracked';
ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS daily_quantity INTEGER NULL;

COMMIT;

-- Contrôle après application : 6 lignes attendues.
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND ((table_name = 'online_stores' AND column_name IN ('fulfilment_shop_id','stock_buffer','low_stock_threshold'))
    OR (table_name = 'online_product_publications' AND column_name IN ('stock_buffer_override','stock_mode','daily_quantity')))
ORDER BY table_name, column_name;

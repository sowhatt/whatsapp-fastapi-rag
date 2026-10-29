# Matrice de propriété et dépendances — J4.3A

Référence Online : `e34ea2f0d9c5f3270129e4b163e373f701f84520`.
Inventaire reproductible : `python -B -m scripts.j43a.inventory` (aucune connexion DB).
[JSON complet](orm_inventory.json) : colonnes, nullabilité, PK, FK, uniques et index.
**Exhaustif pour les 34 tables ORM de cette référence**, complété ci-dessous par le SQL analytique et les modèles externes committés. Le namespace ORM n'est pas explicite : `public` est la cible du laboratoire ; le `search_path` réel doit être vérifié avant J4.3B. Ce document ne certifie pas le catalogue Railway courant ni les travaux non committés.

Les propriétaires sont des domaines métier, pas les propriétaires PostgreSQL constatés en staging. Les attributions cibles Core des catalogues/identifiants partagés sont proposées dans l'ADR ; les credentials restent exclusivement Auth.

## Codes de lecture

- **C** : `j43a_core_runtime` ; **O** : `j43a_online_runtime` ; **W** : `j43a_worker`. Droits détaillés dans `003_security.sql`. Aucun runtime n'est propriétaire. Le rôle de migration est distinct.
- **R** : politique tenant `USING` + `WITH CHECK`, ENABLE/FORCE RLS dans le laboratoire. Pas de clause `app.rls_bypass`. Les NULL historiques sont invisibles ; ne pas leur affecter un marchand arbitraire.
- **D** : RLS forcée sans policy ni GRANT, refus total pour les enfants Shop sans colonne tenant. **G** : référentiel global, sans RLS, aucun droit applicatif du laboratoire.
- **MC** : ne pas copier maintenant ; inventaire, réconciliation, coupure contrôlée de tous les writers puis transfert de l'autorité vers Core après ADR. Conserver identifiants et séquences, jamais deux stocks autoritaires.
- **MO** : export sélectif Online après réconciliation ; préserver identifiants, références, timestamps et reçus. Références Core deviendront logiques validées côté Core, pas des FK inter-bases.
- **MS** : reste dans Shop, aucune migration J4.3A, aucun changement de son code/base. Les répliques synthétiques du laboratoire ne sont pas Shop réel.
- **SC** : commandes Core et événements versionnés vers projections en lecture seule ; jamais de réplication bidirectionnelle de stock.
- **SO** : données privées Online ; outbox locale, inbox dédupliquée, identité Core stable ; aucune écriture directe dans Core à terme.
- **SS** : aucun flux nouveau J4.3A ; un futur adaptateur Shop→Core exige autorisation distincte.
- **T1** : actuellement checkout/commande/Core/réservations/outbox dans une seule transaction SQL. **T2** : intégrité catalogue/tenant. **T3** : transaction Shop conservée. **T4** : atomicité locale message/effet, livraison au moins une fois. **T5** : référentiel historique Shop.

## Tables de la référence Online

Dans « RLS source », `oui+bypass` signifie que le code d'installation contient une policy permettant `app.rls_bypass=true` ; ce n'est pas une preuve de protection effective d'un runtime SUPERUSER/BYPASSRLS.

| Schéma.table | Propriétaire cible | PK ; FK (colonne → cible) | Dépendances et contrainte transactionnelle | RLS source → labo | Rôle labo | Migration ; synchronisation |
| --- | --- | --- | --- | --- | --- | --- |
| public.business_transactions | Core | id ; merchant_id → merchants.id | Racine métier, statut/paiement atomiques avec commande et événements (T1). | oui+bypass → R | C (SIU) | MC ; SC |
| public.categories | Core | id ; merchant_id → merchants.id (NULL) | Identité catalogue ; catégorie du même marchand (T2). | absente du code source → R | C (SIU) ; O (S) | MC ; SC |
| public.currencies | Shop | id ; aucune FK | Référentiel devise ; aucun runtime Online autorisé (T5). | absente du code source → G | aucun | MS ; SS |
| public.customers | Shop | id ; merchant_id → merchants.id (NULL) | Identité client tenant ; aucune copie des données privées vers Online (T3). | absente du code source → R | aucun | MS ; SS |
| public.exchange_rates | Shop | id ; base_currency_id → currencies.id ; quote_currency_id → currencies.id | Deux références devises ; taux daté ; aucun runtime Online autorisé (T5). | absente du code source → G | aucun | MS ; SS |
| public.financial_entries | Shop | id ; merchant_id → merchants.id (NULL) | Journal financier tenant ; liens métier à préserver (T3). | absente du code source → R | aucun | MS ; SS |
| public.merchants | Core | id ; aucune FK | Identifiant tenant partagé ; provisionnement distinct des credentials Auth (T2). | absente du code source → R | C (SIU) ; O (S) | MC ; SC |
| public.online_cart_items | Online | id ; cart_id → online_carts.id ; merchant_id → merchants.id ; product_id → products.id | Quantité/prix par panier-produit unique ; même tenant que parents (T1). | absente du code source → R | O | MO ; SO |
| public.online_carts | Online | id ; merchant_id → merchants.id ; store_id → online_stores.id | Token unique ; un checkout par panier (T1). | absente du code source → R | O | MO ; SO |
| public.online_notifications | Online | id ; aucune FK | source_event_id unique ; matérialisation et reçu inbox atomiques à terme (T4). | oui+bypass → R | O (S + U lecture), W (SIU) | MO ; SO |
| public.online_order_items | Online | id ; merchant_id → merchants.id ; order_id → online_orders.id ; product_id → products.id | Snapshots immuables après checkout ; ensemble égal aux réservations (T1). | absente du code source → R | O | MO ; SO |
| public.online_orders | Online | id ; cart_id → online_carts.id ; merchant_id → merchants.id ; store_id → online_stores.id ; transaction_id → business_transactions.id | Panier et transaction uniques ; état/paiement synchrones avec Core actuellement (T1). | absente du code source → R | O | MO ; SO |
| public.online_product_images | Online | id ; merchant_id → merchants.id ; product_id → products.id | Média privé référencé par identité Core (T2). | absente du code source → R | O | MO ; SO |
| public.online_product_publications | Online | id ; merchant_id → merchants.id ; product_id → products.id | Unique tenant/produit et tenant/slug SEO ; publication indépendante de Shop (T2). | absente du code source → R | O | MO ; SO |
| public.online_stores | Online | id ; merchant_id → merchants.id | Merchant et slug uniques ; publication tenant (T2). | absente du code source → R | O | MO ; SO |
| public.open_tab_items | Shop | id ; merchant_id → merchants.id (NULL) ; product_id → products.id (NULL) ; tab_id → open_tabs.id | Encours/produit et marchand concordants ; produit parfois NULL (T3). | absente du code source → R | aucun | MS ; SS |
| public.open_tabs | Shop | id ; merchant_id → merchants.id (NULL) | Encours Shop ; lignes dépendantes, tenant nullable historique (T3). | absente du code source → R | aucun | MS ; SS |
| public.outbox_events | Online | id ; aucune FK | Événement et mutation dans le même commit ; event_id unique ; pas de transport avant commit (T4). | oui+bypass → R | C/O (SI), W (S + U colonnes de livraison) | MO ; SO |
| public.payment_allocations | Shop | id ; payment_id → payments.id ; sale_item_id → sale_items.id | Tenant indirect via paiement ET ligne de vente ; vérifier leur concordance (T3). | absente du code source → D | aucun | MS ; SS |
| public.payments | Shop | id ; customer_id → customers.id (NULL) ; merchant_id → merchants.id (NULL) ; sale_id → sales.id | Affectations et solde liés à vente/client ; pas de doublon lors d’un rejeu (T3). | absente du code source → R | aucun | MS ; SS |
| public.product_images | Shop | id ; merchant_id → merchants.id ; product_id → products.id | Médias du catalogue Shop ; distincts des médias Online (T2). | absente du code source → R | aucun | MS ; SS |
| public.product_publications | Shop | id ; merchant_id → merchants.id ; product_id → products.id | Catalogue WhatsApp ; unique tenant/produit ; distinct des publications Online (T2). | absente du code source → R | aucun | MS ; SS |
| public.products | Core | id ; category_id → categories.id (NULL) ; merchant_id → merchants.id (NULL) | Autorité produit/stock ; verrou produit ordonné avant réservation (T1). | absente du code source → R | C (SIU) ; O (S) | MC ; SC |
| public.purchase_items | Shop | id ; product_id → products.id ; purchase_id → purchases.id | Tenant indirect via achat ; produit Core (T3). | absente du code source → D | aucun | MS ; SS |
| public.purchases | Shop | id ; merchant_id → merchants.id (NULL) ; supplier_id → suppliers.id (NULL) | Achat, stock, fournisseur, coût/devise liés (T3). | absente du code source → R | aucun | MS ; SS |
| public.sale_items | Shop | id ; product_id → products.id ; sale_id → sales.id | Dépendance tenant indirecte via vente ; produit Core ; coût/prix snapshots (T3). | absente du code source → D | aucun | MS ; SS |
| public.sales | Shop | id ; customer_id → customers.id (NULL) ; merchant_id → merchants.id (NULL) | Vente et lignes/paiement/mouvement dans transaction Shop ; transaction métier future Core (T3). | absente du code source → R | aucun | MS ; SS |
| public.stock_movements | Core | id ; merchant_id → merchants.id (NULL) ; product_id → products.id | Journal de stock Shop actuel, autorité cible Core ; référence logique polymorphe (T3). | absente du code source → R | C (SIU) | MC ; SC |
| public.stock_reservations | Core | id ; merchant_id → merchants.id ; product_id → products.id | Ensemble complet, quantités positives, échéance relue après verrou ; active/consumed/released/expired (T1). | absente du code source → R | C (SIU) | MC ; SC |
| public.supplier_payment_allocations | Shop | id ; purchase_item_id → purchase_items.id ; supplier_payment_id → supplier_payments.id | Tenant indirect via paiement fournisseur ET ligne achat (T3). | absente du code source → D | aucun | MS ; SS |
| public.supplier_payments | Shop | id ; merchant_id → merchants.id (NULL) ; purchase_id → purchases.id ; supplier_id → suppliers.id (NULL) | Paiement achat/fournisseur atomique avec affectations (T3). | absente du code source → R | aucun | MS ; SS |
| public.suppliers | Shop | id ; merchant_id → merchants.id (NULL) | Nom unique par marchand ; historique achat à conserver (T3). | absente du code source → R | aucun | MS ; SS |
| public.transaction_events | Shop | id ; merchant_id → merchants.id (NULL) | Journal Shop polymorphe ; pas un transport outbox Core (T3). | absente du code source → R | aucun | MS ; SS |
| public.web_push_subscriptions | Online | id ; aucune FK | Endpoint global unique ; refus réattribution inter-tenant ; worker lecture seule (T4). | oui+bypass → R | O ; W (S) | MO ; SO |

Les uniques/index uniques sont détaillés dans le JSON : des `unique=True,index=True` ORM deviennent des index uniques, pas nécessairement des `UniqueConstraint` Python. Les FK simples de la source ne garantissent pas le même tenant ; `004_tenant_references.sql` ajoute 13 FK composites dans le laboratoire Core–Online. Ne pas transposer ces FK entre bases physiques.

## SQL hors ORM

| Objet / schéma par défaut | Domaine | PK / FK / dépendances | Transaction / RLS / rôle | Migration / synchronisation |
| --- | --- | --- | --- | --- |
| public.fact_inventory_daily_snapshot | Shop analytique | PK id ; unique(snapshot_date,merchant_id,product_id) ; aucune FK déclarée | Snapshot journalier dérivé ; pas de policy dans le SQL ; aucun rôle labo | MS ; reconstruire depuis un watermark cohérent seulement après validation |
| public.mv_customer_financial_position | Shop analytique | Vue matérialisée ; clients, ventes, paiements/affectations ; pas de PK/FK de table | Refresh cohérent ; accès agrégé privé à ne pas exposer par simple GRANT | MS ; reconstruction Shop, aucune copie Online |
| public.mv_supplier_financial_position | Shop analytique | Vue matérialisée ; fournisseurs, achats, paiements/affectations | Idem | MS ; SS |
| public.mv_stock_analytics | Shop analytique | Vue matérialisée ; produits et métriques de stock | Idem ; la vue matérialisée n'hérite pas automatiquement des garanties RLS des tables source | MS ; SS |
| public.mv_daily_business_metrics | Shop analytique | Vue matérialisée ; ventes, achats et finance journalière | Idem | MS ; SS |
| public.mv_product_profitability | Shop analytique | Vue matérialisée ; produits, lignes ventes/achats | Idem | MS ; SS |
| public.mv_currency_purchase_exposure | Shop analytique | Vue matérialisée ; achats et devises | Idem | MS ; SS |

Sources : `app/analytics/sql/*.sql`. Les migrations de laboratoire n'installent ni cette table ni ces vues, car elles ne sont pas requises par Online. `app/main.py` contient également des DDL incrémentaux historiques : la baseline ORM n'est **pas** une migration de mise à niveau d'une base existante.

## Complément externe Auth/Shop, lecture seule

Source locale committée : `whatzabi-shop-integration`, commit `bcdecabb484b6e72bdb99672b278c405217f2162`.
[Inventaire AST](external_schema_inventory.json) : 48 tables modèles, dont 22 également présentes par nom dans Online ; les définitions peuvent diverger. Aucun module externe importé/exécuté, aucun travail non committé intégré. Cette lecture complète la cartographie ; elle ne valide ni les migrations appliquées ni la version déployée de cette source.

Pour toutes les lignes ci-dessous : schéma non explicite (`public` à confirmer), rôle autorisé **Auth ou Shop dédié selon propriétaire, aucun C/O/W du laboratoire** ; RLS effective **non attestée par cet inventaire de modèles**. Traitement **MA** = laisser les données et migrations sous l'autorité Auth, pas de copie de secrets/sessions ; synchronisation **SA** = identité/autorisation vérifiée par contrat Auth, jamais la table de credentials. **MS/SS** conservent le sens ci-dessus. Les PK/FK ci-dessous proviennent des colonnes ORM ; les contraintes composites et ajouts SQL doivent être comparés au catalogue lors de l'audit préalable J4.3B.

| Table supplémentaire | Domaine | PK | FK et dépendances | Contrainte métier ; migration/sync |
| --- | --- | --- | --- | --- |
| activation_invitations | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| admin_users | Auth | id | aucune FK de colonne ORM ; identifiants logiques à contrôler | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_auth_attempts | Auth | merchant_id,user_id,purpose | merchant_id → merchants.id ; user_id → merchant_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_auth_devices | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_auth_sessions | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id ; shop_id → shops.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_passkey_challenges | Auth | id | shop_id → shops.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_passkey_rate_limits | Auth | bucket | aucune FK de colonne ORM ; identifiants logiques à contrôler | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_passkey_users | Auth | user_id | user_id → merchant_users.id ; merchant_id → merchants.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_passkeys | Auth | id | aucune FK de colonne ORM ; identifiants logiques à contrôler | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_pin_credentials | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| merchant_users | Auth | id | merchant_id → merchants.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| product_barcodes | Core cible (actuel Shop) | id | merchant_id → merchants.id ; product_id → products.id | Identité produit ou stock par boutique à intégrer au contrat Core ; aucune migration avant ADR ; MC/SC |
| product_references | Core cible (actuel Shop) | id | aucune FK de colonne ORM ; identifiants logiques à contrôler | Identité produit ou stock par boutique à intégrer au contrat Core ; aucune migration avant ADR ; MC/SC |
| sale_photo_imports | Shop | id | merchant_id → merchants.id ; shop_id → shops.id ; sale_id → sales.id | Scope boutique et transaction Shop ; MS/SS |
| security_assignments | Auth | id | request_id → security_requests.id ; admin_id → admin_users.id ; assigned_by → admin_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_audit | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id ; admin_id → admin_users.id ; request_id → security_requests.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_mandates | Auth | id | admin_id → admin_users.id ; merchant_id → merchants.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_notifications | Auth | id | request_id → security_requests.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_requests | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_reviews | Auth | id | request_id → security_requests.id ; admin_id → admin_users.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| security_subjects | Auth | user_id | merchant_id → merchants.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| shop_inventories | Core cible (actuel Shop) | id | merchant_id → merchants.id ; shop_id → shops.id ; product_id → products.id | Identité produit ou stock par boutique à intégrer au contrat Core ; aucune migration avant ADR ; MC/SC |
| shop_operations | Shop | id | merchant_id → merchants.id ; shop_id → shops.id ; user_id → merchant_users.id | Scope boutique et transaction Shop ; MS/SS |
| shops | Shop | id | merchant_id → merchants.id | Scope boutique et transaction Shop ; MS/SS |
| user_phones | Auth | id | merchant_id → merchants.id ; user_id → merchant_users.id ; shop_id → shops.id | Identité, révocation, challenge ou contrôle sécurité ; MA/SA |
| user_shop_memberships | Shop | id | user_id → merchant_users.id ; shop_id → shops.id | Scope boutique et transaction Shop ; MS/SS |
| merchant_auth_schema_versions | Auth | version | aucune FK ; migration 001_s1_5_pin_enrollment.sql | Journal migrations Auth ; MA, aucune synchronisation |

Les objets externes `shop_inventories`, `product_barcodes` et `product_references` montrent que le modèle de stock réel peut être plus riche que `products.stock` dans la référence Online. Décision bloquante : scope de stock marchand/boutique, unités, identité produit, correspondance des IDs entre versions. Une extraction basée uniquement sur les 34 tables Online serait incomplète.

## Tables nouvelles du laboratoire

| Table | Domaine préparatoire | PK / FK | RLS / droits | Migration / synchronisation |
| --- | --- | --- | --- | --- |
| command_receipts | Core | (merchant_id,source,idempotency_key) ; merchant→merchants | R ; C SIU | 002 ; commande, empreinte, résultat et effet dans transaction locale ; pas d'expiration automatique du reçu |
| inbox_receipts | Online (une inbox par consommateur/autorité à terme) | (merchant_id,consumer,event_id) ; merchant→merchants | R ; O/W SIU | 002 ; déduplication atomique avec effet local ; pas de publication distante ici |
| schema_migrations | Infrastructure locale | version ; sha256 | aucun runtime ; propriétaire/migrateur seulement | journal, checksums obligatoires, transaction et verrou advisory |

## Écritures croisées identifiées

- `app/domains/online/public/checkout.py` crée `business_transactions`, commande/lignes, réservations et outbox avant **un** commit ; lit/verrouille les produits.
- `app/domains/online/internal/order_service.py` et `payment_service.py` synchronisent la racine Core, mutent les réservations et publient via l'outbox de la même session. `mutation.py` rollback toute erreur ; les flush J4.2.1 rendent expiration/libération visibles avec `autoflush=False` sans commit intermédiaire.
- `app/domains/core/public/stock.py` maintient les consommations Online comme réservations `consumed`, sans décrémenter `products.stock`. Shop ne déduit pas ces consommations dans son catalogue.
- `app/routers/sales.py` décrémente puis restitue le stock lors d'annulation ; `app/routers/purchases.py` incrémente/décrémente ; `app/services/catalog_service.py` peut remplacer directement le stock. Ces writers ne sont pas migrés par J4.3A.
- `outbox_events` est aujourd'hui partagé par les effets Online/Core et notifications. La cible exige une outbox par base propriétaire, pas une table SQL accessible depuis toutes les bases.
- Les FK produits/merchants/transactions et les identifiants polymorphes `source_type/source_id`, `reference_type/reference_id`, `shop_id` non FK sont des dépendances inter-domaines, même sans contrainte SQL.

**Conséquence : aucune garantie de non-survente globale Shop+Online ne découle des tests Online actuels.** Les tests prouvent la concurrence Online sur une autorité SQL unique. Faire passer tous les writers Shop par Core nécessite une autorisation et une livraison distinctes.

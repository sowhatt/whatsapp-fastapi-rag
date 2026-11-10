# Préparation de la séparation migrations / runtime web

Audit local à partir de `56b866a`. Aucune modification du runtime, de Shop, d'Auth V2 ou des paramètres de service. Ce document prépare une livraison ultérieure ; il n'active pas de mode de migration.

## État observé

`app/online_main.py:ensure_online_schema`, enregistré sur l'événement FastAPI `startup`, ouvre `engine.begin()` et appelle les huit installateurs suivants, dans cet ordre. L'engine de `app/db/session.py` utilise le même `settings.database_url` que les requêtes web. Chaque processus web qui déclenche le startup peut donc lancer ces DDL.

| Installateur | Module | Objets / opérations |
| --- | --- | --- |
| `install_foundation_rls` | `app/shared/tenancy/rls.py` | `business_transactions`, index, ENABLE/FORCE RLS, DROP/CREATE policy |
| `install_outbox_schema` | `app/shared/outbox/schema.py` | `outbox_events`, ajouts colonnes de livraison, index, ENABLE/FORCE RLS, DROP/CREATE policy |
| `install_online_notifications_schema` | `app/shared/notifications/schema.py` | `online_notifications`, index, ENABLE/FORCE RLS, DROP/CREATE policy |
| `install_web_push_schema` | `app/shared/notifications/push_schema.py` | `web_push_subscriptions`, index, ENABLE/FORCE RLS, DROP/CREATE policy |
| `install_online_schema` | `app/domains/online/internal/schema.py` | `online_stores`, publications/images, colonnes SEO/capacités, index |
| `install_online_cart_schema` | `app/domains/online/internal/cart_schema.py` | paniers/lignes, FK, index |
| `install_online_order_schema` | `app/domains/online/internal/order_schema.py` | commandes/lignes, FK, index, colonne `payment_method` |
| `install_stock_reservation_schema` | `app/domains/core/internal/stock_schema.py` | réservations, FK, index |

Le startup Shop distinct, `app/main.py:ensure_catalog_schema`, contient des DDL et des backfills métier ; il reste hors périmètre. Le `Procfile` committé référence `app.main:app` : ce fichier ne prouve pas quel entrypoint est effectivement configuré à distance. Aucune inspection ou modification Railway n'a été faite.

## Problèmes à ne pas transporter dans le migrateur

- Les installateurs historiques n'ont pas de journal version/SHA-256 ni de verrou de migration inter-processus. `IF NOT EXISTS` ne vérifie pas la conformité d'un objet déjà présent.
- Les quatre modules RLS historiques recréent des policies contenant une branche `app.rls_bypass`. Les déplacer tels quels pourrait réintroduire une autorisation permissive à côté des policies strictes du laboratoire. Aucune de ces policies historiques n'est appliquée au schéma J4.3A par cette livraison.
- Un rôle runtime minimal doit refuser ces DDL. Le rendre propriétaire ou membre du migrateur pour permettre le startup annulerait la séparation des privilèges.
- Les tests HTTP existants utilisent souvent `TestClient(app)` sans contexte de lifespan ; leur succès ne prouve pas qu'un startup réel fonctionne avec les rôles minimaux. Les tests PostgreSQL ajoutés prouvent au contraire les refus DDL attendus.

## Contrat de la future livraison

1. Inventorier le schéma réellement ciblé dans une étape autorisée. Transformer chaque changement nécessaire en migration versionnée et revue, avec préconditions et contrôle de dérive. Ne pas exécuter la baseline locale sur une base existante et ne pas copier les anciennes policies à bypass.
2. Fournir une commande de migration indépendante, sans import de l'application ASGI ni création de son engine. Connexion de migration explicitement fournie, sans repli sur `DATABASE_URL` runtime ; credential et processus séparés. Le web et les workers ne reçoivent ni ce secret ni le droit `SET ROLE` owner/migrator.
3. Reprendre le principe éprouvé de `Lab.migrate` : journal version + empreinte, verrou transactionnel unique, migration atomique, refus en cas de checksum divergent. Adapter les préconditions au schéma réel et le traitement des DDL non transactionnels si nécessaires ; aucun backfill Shop/Auth dans ce lot.
4. Remplacer le handler startup Online par une vérification **en lecture seule** de compatibilité de schéma (version/empreinte attendue). Schéma absent ou incompatible : readiness refusée et erreur explicite, aucun auto-repair DDL. Prévoir une vue ou un droit de lecture ciblé du journal, aujourd'hui interdit aux runtimes du laboratoire.
5. Valider sur une instance jetable : installation vierge, upgrade depuis une version supportée avec données, relance identique, deux migrateurs concurrents, rollback d'une erreur, drift détecté, startup ASGI complet avec login runtime non propriétaire, journal incorrect/absent refusé, aucune DDL au startup ni à la première requête. Conserver les tests négatifs RLS/ACL et les tests métier.
6. Après ces preuves et une autorisation distincte, préparer l'ordre migrateur puis web/worker et un rollback compatible. Aucun changement de service n'est réalisé ici.

Le lanceur actuel `scripts.j43a.run` reste exclusivement local : il utilise des conteneurs qu'il vient de créer, jamais un DSN opérationnel. Il constitue une preuve de mécanisme, pas la commande de migration de production. La suppression effective du DDL startup, la validation d'identité et la compatibilité du runtime minimal restent des bloqueurs de J4.3B.

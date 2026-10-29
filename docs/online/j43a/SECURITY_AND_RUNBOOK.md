# Sécurité, recette et retour arrière J4.3A

## Exécution locale reproductible

Prérequis : Docker local via socket Unix, Python 3.12 avec les dépendances du projet, pytest, SQLAlchemy, psycopg et psycopg2. L'image est fixée à PostgreSQL **18.6**, digest `sha256:979bccfde35445db618c65107d27d08c6c21339d8dc3ad4c830c6633947be0e4` (image Docker officielle utilisée ici). Prévoir accès au registre uniquement si cette image n'est pas en cache.

Depuis la racine Online, avec le Python du venv :

```sh
python -B -m scripts.j43a.run --report-dir docs/online/j43a/evidence
```

Le lanceur n'accepte **aucun DSN, hôte de base, conteneur existant ou service Railway**. Il crée deux conteneurs à noms aléatoires sur un réseau Docker propre, volumes de données en tmpfs, ports publiés uniquement sur `127.0.0.1`. Les paramètres d'environnement de connexion DB ne sont pas transmis aux tests ; `DATABASE_URL=sqlite://` pour les tests unitaires, ports PostgreSQL construits par le lanceur. Il vérifie `server_version_num=180006`, labels de propriété et hôte Docker local. Le plugin de test refuse les connexions Python non loopback ; les connexions des drivers PostgreSQL utilisent exclusivement les URL locales construites. Le réseau Docker est un bridge dédié, pas une garantie générale de filtrage réseau du poste.

L'authentification `trust` est **réservée à ces conteneurs synthétiques éphémères**, sans données ni credentials réels. Elle ne constitue pas une configuration staging. Aucun volume d'un conteneur existant n'est monté. La suppression cible uniquement les IDs créés par le lanceur après vérification du label de ce run. Même en échec, les ressources sont nettoyées ; un arrêt brutal du processus nécessite un nettoyage manuel des seuls IDs/labels du run, jamais un `docker prune`.

Les tests PG18.6 obligatoires échouent si le laboratoire manque. Le mode de recette fait également échouer la suite si un test est ignoré. Les tests J4.2 conservent leur ancienne option PG16 pour usage historique, mais J4.3A exige exactement 18.6 et ne passe pas par cette option.

## Rôles et droits du laboratoire

| Rôle | Login / privilèges | Portée |
| --- | --- | --- |
| j43a_owner | NOLOGIN, NOSUPERUSER, NOBYPASSRLS | Propriétaire des objets, RLS forcée ; aucune application membre |
| j43a_migrator | LOGIN, NOINHERIT, sans super/bypass/create role/create DB/replication ; seul membre de owner | SET ROLE explicite pendant les migrations ; credential d'exploitation distinct, jamais runtime |
| j43a_core_runtime | LOGIN, aucun rôle supérieur | SELECT/INSERT/UPDATE Core, SELECT/INSERT outbox ; séquences nécessaires ; aucune table Shop |
| j43a_online_runtime | LOGIN, aucun rôle supérieur | DML Online selon usage ; produits/catalogue/merchant en lecture ; outbox SI ; notifications S + colonnes de lecture U ; aucun DML Core/Shop |
| j43a_worker | LOGIN, aucun rôle supérieur | Tenant-scoped ; lecture outbox, modification des seules colonnes de livraison, notifications/inbox, lecture subscriptions ; aucun produit/commande/Shop |

Tous ces rôles sont sans SUPERUSER/BYPASSRLS/CREATEDB/CREATEROLE/REPLICATION. PUBLIC perd CONNECT/TEMP sur la base et CREATE/USAGE sur `public` ; seuls les rôles explicites reçoivent CONNECT/USAGE. Pas de TRUNCATE, DDL, changement de policy ou accès au rôle de migration pour les runtimes. Les droits séquences sont explicites. Le bootstrap utilise l'administrateur **du conteneur jetable** pour créer rôles/base ; les assertions de sécurité utilisent les vrais logins applicatifs non propriétaires.

Les 28 tables ORM à tenant direct, deux tables de reçus et quatre enfants Shop sans tenant direct ont ENABLE/FORCE RLS : 34 tables privées protégées dans le labo. Les quatre enfants Shop sont fermés sans policy ni GRANT. Devises/taux sont sans permission runtime. Les politiques tenant n'ont aucune branche `app.rls_bypass`, et les tests tentent explicitement de la forger.

Le tenant est fixé avec `set_config(...,true)` **dans chaque transaction**, avant toute requête. Après commit/rollback, il faut le réappliquer ; le pool ne transporte pas l'identité. Les tests couvrent commit, rollback, erreur SQL, pool réutilisé et références produit d'un autre tenant. Une GUC tenant n'est pas un mécanisme d'authentification : un client disposant directement du login SQL pourrait choisir une autre valeur. Les credentials restent exclusivement serveur, l'identité doit être vérifiée, pas de SQL fourni par le client. La connexion publique storefront doit être redessinée avant activation de cette RLS généralisée.

Ces rôles constituent un socle de revue, pas un GO runtime. En particulier le runtime historique exécute du DDL, écrit directement Core depuis Online et ne remet pas encore le contexte sur toutes les lectures. Le rôle minimal doit le refuser ; augmenter ses droits pour le faire passer serait une régression.

## Migrations locales

1. Bootstrap rôles/base par `Lab.bootstrap`, noms fixes seulement dans le conteneur possédé.
2. `001_baseline.sql` : 34 tables ORM figées à la référence, sans dépendance à un futur `create_all` dynamique. Schéma vierge uniquement, données synthétiques.
3. `002_receipts.sql` : reçus commande/inbox préparatoires.
4. `003_security.sql` : droits explicites et policies tenant.
5. `004_tenant_references.sql` : fermeture des enfants Shop du labo, FK composites et quantités positives Core/Online.

Le journal `schema_migrations` stocke nom et SHA-256 ; verrou advisory, transaction unique, replay sans réappliquer la DDL ; modification d'un fichier déjà appliqué = erreur. Aucun down destructif n'est livré. La baseline n'est pas une extraction de données ni une migration d'upgrade du schéma Railway. Les contraintes composites ne peuvent pas être conservées telles quelles entre bases physiques : le futur schéma dédié dépend de l'ADR.

`scripts/j43a/verify_readonly.sql` et `reconcile_readonly.sql` sont des requêtes de revue, avec transaction READ ONLY et timeout. Elles ne sont jamais lancées à distance par le sprint. Le second script vise la base co-localisée historique ; les résultats sous RLS sont limités au périmètre visible. Aucun résultat vide ne prouve l'absence globale d'anomalies. Pour une campagne ultérieure, définir explicitement le rôle d'audit en lecture, les tenants autorisés et le snapshot de lecture.

## Sauvegarde/restauration testée

Le test crée des marchands, produits, paniers, commandes, réservations, événements et reçus synthétiques, puis :

1. Capture des empreintes de **toutes** les lignes par table, état `last_value/is_called` des séquences, contraintes, index, policies RLS, propriétaires, ACL tables/colonnes, permissions effectives, flags et memberships des rôles, ACL schéma/base.
2. `pg_dump -Fc --create` avec l'outil 18.6 du conteneur source ; archive conservée uniquement en mémoire pour le test. Aucune donnée de Shop réel n'est exportée.
3. Création du manifeste de rôles dans le second cluster vide, puis `pg_restore --exit-on-error --create` vers sa base `postgres`. Les rôles sont globaux au cluster et ne sont pas inclus dans un dump de base : le manifeste est indispensable. Aucun hash de mot de passe n'est exporté.
4. Comparaison complète avant/après, puis replay des migrations sur le journal restauré. Les ACL NULL (droits par défaut) sont normalisées avec `acldefault`, sans ignorer les droits effectifs. Le CHECK du reçu est écrit sous une forme stable au dump/restore.
5. Vérification de la prochaine valeur de séquence, refus de mutation Core par Online, isolation A/B et FK réellement active sur la base restaurée.

L'administrateur du laboratoire sert à une sauvegarde exhaustive et à l'import, pas aux tests de permissions. Aucune policy n'est désactivée pour réussir un test. `pg_dump` vérifie nativement qu'il peut lire la totalité des données ; un rôle soumis à RLS sans visibilité globale n'est pas un rôle de sauvegarde exhaustive.

Cette preuve établit la restaurabilité de la **base synthétique du laboratoire**. Elle ne prouve ni la présence d'une sauvegarde Railway, ni sa fraîcheur, ni le RPO/RTO sur volumes réels. L'archive locale éphémère n'est pas une sauvegarde de staging. Les runtimes n'obtiennent jamais les droits du compte de sauvegarde ; le rôle opérationnel de sauvegarde/PITR reste à définir avec D6.

Références PostgreSQL 18 : [RLS](https://www.postgresql.org/docs/18/ddl-rowsecurity.html), [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html). Les rôles sont des objets de cluster ; les tables propriétaires et SUPERUSER/BYPASSRLS exigent un contrôle distinct des policies.

## Ordre proposé J4.3B — aucune étape exécutée ici

| Étape | Action soumise à autorisation ultérieure | Critère d'acceptation / arrêt |
| --- | --- | --- |
| 0 | Valider ADR D1–D6 et périmètre Shop/Auth, versions/IDs réels | Pas de writer non inventorié ; pas de décision implicite sur le stock boutique |
| 1 | Refaire audit lecture seule Railway : projet/env/service/DB/roles, provenance de l'image, migrations et backups | Correspondances identifiées sans valeurs de secrets ; staging distinct production ; inventaire réel comparé à la matrice |
| 2 | Définir et éprouver image applicative compatible, migrations dédiées, protocole Core et adaptateurs autorisés | Tests deux bases + crash/réseau + non-survente globale ; pas de DDL runtime ni bypass |
| 3 | Valider la réconciliation et restauration de sauvegarde autorisée sur instance isolée | Zéro anomalie inexpliquée ; rôles/RLS/contraintes/data/sequences concordants ; RPO/RTO mesurés |
| 4 | Provisionner Core/Online staging dédiés, rôles et secrets séparés | Aucun endpoint/credential partagé avec Shop/production ; workers séparés et désactivés pendant copie |
| 5 | Arrêter les writers concernés par protocole approuvé, fixer watermark et backup final | Absence de transactions en vol ; pas de double écriture ; capacité de retour testée |
| 6 | Copier sélectivement et valider toutes les données, références logiques et compteurs | Comptes/hashes par tenant, aucun orphelin/doublon, valeurs stock/réservations attestées |
| 7 | Démarrer Core puis Online compatible, garder trafic fermé, rattraper événements | Health/readiness, auth admin réelle, migrations concordantes, file sans erreurs |
| 8 | Recette A/B, panier multi-articles, concurrence, retry ambigu, expiration, annulation, paiements, projections et rollback | Aucun effet double ni fuite tenant ; seuils de monitoring validés ; abort immédiat sur divergence |
| 9 | Ouvrir progressivement sous observation, conserver backup et version antérieure compatible | Validation métier et exploitation ; journal du point de bascule et des opérations nouvelles |

Les noms de paramètres à prévoir sont séparés (`ONLINE_DATABASE_URL`, `CORE_DATABASE_URL`, `CORE_API_BASE_URL`, identifiants du worker et du migrateur). Ce sont des **paramètres cibles**, non reconnus/configurés par cette livraison. Aucun secret ou référence Railway à modifier n'est fourni. Le runtime actuel lit toujours `DATABASE_URL`.

## Réconciliation historique préparée, sans écriture

Pour chaque anomalie, conserver evidence hash, tenant, IDs, versions, quantités, devise, paiement, dates et source ; revue métier et décision signée avant correction. Lire un snapshot cohérent avec permissions d'audit adaptées ; une ligne invisible en RLS n'est pas une ligne absente.

- Commande completed / racine Core pending : prouver le journal de consommation et l'ensemble des articles ; proposer uniquement le rattrapage de statut/paiement compatible. **Ne pas rappeler Consume/RecordSale** comme moyen de synchronisation, sous peine de compter le stock deux fois.
- Réservation active mais expirée : conserver l'échéance passée ; décider expiration puis revalidation complète sous verrous si la commande reste payable. Ne jamais ressusciter une ancienne réservation par simple mise à jour du timestamp.
- Tenant différent, racine orpheline, doublon de source/clé, quantité invalide ou stock incohérent : quarantaine logique et revue ; aucune réparation par changement arbitraire de merchant/product.
- Événement pending/published : distinguer notification et événement métier ; inventaire des consommateurs et des reçus avant tout rejeu. Ne pas republier aveuglément des paiements/notifications déjà exécutés.
- Stock physique, consumed Online et inventaires boutique : rapprocher journal et soldes, établir une valeur d'ouverture Core signée ; ne jamais soustraire deux fois les consommations historiques.

Le contexte de mission indique des anomalies J4.2.1 ; aucune ligne distante n'a été relue ou corrigée ici. Les IDs et comptes antérieurs ne sont pas certifiés à la date de ce rapport. Les tests synthétiques J4.2.1 valident la mécanique de rollback/revalidation, pas une autorisation de réparation de l'historique.

## Retour arrière compatible avec une base dédiée

Avant ouverture, le retour consiste à garder le trafic fermé, arrêter uniquement les nouveaux workers et abandonner les instances candidates après conservation des preuves. Shop n'est jamais restauré ni modifié par ce retour.

Après ouverture et nouvelles écritures, ne pas repointer Online vers l'ancienne base partagée : elle n'a pas reçu les opérations et l'ancien binaire suppose une transaction commune. Revenir à une **image antérieure compatible avec le schéma dédié et le protocole Core** ; conserver Core comme autorité, conserver reçus/outbox/inbox, arrêter proprement la livraison avant intervention. L'image e34ea2f est une référence source récupérable mais **n'est pas** une image de rollback compatible avec la future séparation.

Si corruption de la base dédiée : fermer les mutations, conserver les journaux et identifiants d'opérations post-backup, restaurer dans une nouvelle instance dédiée, rejouer uniquement les opérations prouvées et dédupliquées, vérifier stock/transactions/événements avant bascule. Si le rapprochement n'est pas prouvable, rester en maintenance et corriger en avant. Une compensation métier est journalisée via Core ; elle n'est pas un rollback SQL inter-bases.

Déclencheurs d'arrêt : fuite tenant, droit excessif, doublon de consommation, incohérence de quantité, timeout ambigu non réconciliable, perte d'événements ou impossibilité de restaurer. RPO/RTO, version de repli compatible et sauvegarde de staging restent des bloqueurs tant qu'ils ne sont pas attestés dans l'étape ultérieure autorisée.

# J4.3A.1 — Corrections de sécurité et verdict de publication

**GO pour publication GitHub de ce commit de corrections locales. NO-GO pour migration physique, activation des rôles en service ou déploiement J4.3B.** Aucun push, merge, déploiement, accès Railway ou écriture distante effectué.

Base vérifiée : `56b866a974363a7298f9f494aa10aa665b8dc51a`, branche `feat/whatzabi-online-j4-3a-db-isolation`, worktree Online initialement propre. La revue indépendante elle-même n'est pas fournie dans le dépôt ; ce lot traite les défauts explicitement listés dans la mission et confirmés dans les sources.

## Corrections livrées

| Défaut | Correction / preuve |
| --- | --- |
| Inbox modifiable/supprimable par le runtime | Migration additionnelle `005_inbox_retention.sql` : retrait UPDATE/DELETE Online et worker ; SELECT conservé, INSERT limité aux quatre colonnes d'identité/empreinte. Tests de refus réels avec les logins non propriétaires, replay toujours dédupliqué, rollback et conflit toujours couverts. |
| Purge sans rôle distinct ni rétention | Rôle `j43a_inbox_maintenance`, sans membership runtime, SELECT/DELETE inbox seulement. Policy restrictive combinée à RLS tenant : rôle exact ET âge strictement supérieur à 2160 heures. Refus DDL, TRUNCATE, INSERT, UPDATE et SET ROLE ; zéro suppression sans tenant, aucune suppression du tenant voisin ou d'un reçu trop récent. |
| Horodatage permettant de raccourcir la conservation | INSERT runtime exclut `processed_at`, default serveur `clock_timestamp()` ; antidatage interdit. Durée en heures indépendante des changements d'heure de la session. Aucun mécanisme de purge automatique activé. |
| Lectures d'audit incohérentes entre requêtes | Les deux scripts SQL utilisent `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`. Exécution des fichiers réels avec commit concurrent : photographie conservée jusqu'au COMMIT, nouvelle ligne visible ensuite, écriture refusée dans le snapshot. |
| Capture Python multi-requêtes | `snapshot()` possède sa transaction REPEATABLE READ READ ONLY et refuse toute transaction préexistante. Test avec UPDATE concurrent intercalé après la première lecture. Comparaison de restauration enrichie : defaults/colonnes et policies restrictives. |
| DDL au démarrage web | Huit installateurs Online audités, plan de transfert et critères d'acceptation documentés dans [STARTUP_SEPARATION.md](STARTUP_SEPARATION.md). Aucune modification du runtime ni des installateurs historiques. |

Les migrations 001–004 sont inchangées, leurs empreintes historiques restent valides. La migration 003 contient donc toujours ses GRANT initiaux ; le schéma final sécurisé s'obtient par **toutes les migrations jusqu'à 005**, appliquées dans la transaction du lanceur. Le bootstrap et le manifeste de restauration comprennent désormais le rôle de maintenance. Le snapshot compare aussi les ACL de colonnes ; l'audit SQL expose ces permissions au lieu de les confondre avec les GRANT de table.

## Recette et preuves

Commande locale, depuis la racine du worktree avec le venv existant :

```sh
../.venv/bin/python -B -m scripts.j43a.run --report-dir docs/online/j43a1/evidence
node tests/merchant_j41_sw_test.cjs
git diff --check
```

Recette finale démarrée le **2026-11-09 à 19:50:06 UTC**, durée du lanceur **18,60 s**. **929 passed, 0 failures, 0 errors, 0 skipped**, dont **61 tests PostgreSQL 18.6** et 868 autres tests Python. La suite complète comprend les non-régressions J4.2/J4.2.1, checkout/réservations/concurrence, outbox/reçus, isolation, contrats Shop figés et adaptateur Auth existant. Le test Node confirme cache, exclusion des API, mode hors connexion et liens Push. `git diff --check` passe.

Le lanceur impose `server_version_num=180006`, image officielle fixée par digest dans [run.json](evidence/run.json), deux instances distinctes jetables. Sauvegarde/restauration, replay du journal, ACL, rôles, RLS, contraintes, données et séquences comparés ; les refus inbox et la protection d'un reçu récent sont également retestés sur la cible restaurée. Les deux conteneurs et le réseau du run ont été supprimés. Aucun service préexistant n'a été arrêté.

La recette préalable a passé 926 tests avant l'ajout des contrôles complémentaires de fuseaux/restauration ; les preuves conservées correspondent au code final, à 929 tests. La première tentative dans le sandbox a été refusée par les permissions du socket Docker, avant création de ressources ; l'exécution locale a ensuite été autorisée via l'escalade prévue.

Preuves : [sortie pytest](evidence/pytest.txt), [JUnit](evidence/pytest.xml), [paramètres et empreintes migrations](evidence/run.json), [manifeste de validation](evidence/validation_manifest.json), [inventaire Git](evidence/git_inventory.json), [test Node](evidence/non_regression.txt). Le manifeste lie les preuves aux empreintes du code testé et à la base Git ; il n'essaie pas d'inclure le hash auto-référent du commit qui le contient.

Les **5629 warnings** de la suite restent présents ; leur détail est masqué par le lanceur historique. Cette livraison ne les corrige pas et ne les assimile pas à des erreurs. Aucun test PostgreSQL n'a été remplacé par SQLite ni ignoré.

## Git, isolation du travail et périmètre

Trois worktrees inventoriés : Online sur la branche attendue, Shop parent sur `feat/s2-5-home-drilldowns` à `71d0582`, ancien worktree temporaire détaché à `e34ea2f` marqué prunable. Le parent contient de nombreux travaux non committés ; aucun nettoyage, reset, checkout ou édition n'y a été réalisé. Statuts et empreintes des fichiers suivis modifiés du parent ont été comparés pendant la tâche ; le résultat est conservé dans l'inventaire. La liste des processus n'était pas accessible dans le sandbox : la vérification de concurrence repose sur les états Git et empreintes, pas sur une prétention d'absence de processus concurrents.

Le diff de livraison est limité à `migrations/j43a_lab`, `scripts/j43a`, `tests/test_online_j43a_postgres.py` et la documentation/preuves. **Aucun fichier `app/`, Shop, Auth V2, Procfile ou configuration de déploiement modifié.** Core n'est pas extrait. Le commit est exclusivement local.

## Risques résiduels et conditions du verdict

- **Purge et rejeu** : 90 jours est un plancher de laboratoire, sans validation d'une fenêtre de replay opérationnelle. Au-delà de la conservation, supprimer un reçu permettrait un nouvel effet lors d'un rejeu ancien. Ne pas activer de purge avant définition des horizons retry/PITR/rejeu et des procédures de gel, d'audit et de traitement des événements anciens. Les anciens reçus ne sont pas réhorodatés par 005. Voir la [politique de rétention](../j43a/SECURITY_AND_RUNBOOK.md).
- **Startup web** : la séparation est préparée, pas exécutée. Le runtime conserve du DDL et les installateurs historiques à policies permissives/bypass ; il reste incompatible avec les rôles minimaux. Ne pas les exécuter sur le schéma sécurisé du laboratoire. La livraison suivante doit retirer ce DDL, introduire le contrôle de compatibilité en lecture seule et prouver le lifespan ASGI complet avec le vrai rôle runtime.
- **Snapshots** : un snapshot couvre une transaction et les données visibles par son rôle/tenant. Il n'établit pas la complétude globale sous RLS, ni une photographie commune entre deux scripts ou entre deux bases. Les séquences ne suivent pas MVCC ; les comparaisons exactes avec dump/restore supposent des writers arrêtés, comme dans ce test synthétique.
- **Identité et administration** : la GUC tenant n'authentifie pas l'utilisateur. Les credentials SQL restent serveur ; les comptes propriétaires/migrateurs et l'administrateur de bootstrap sont des autorités de confiance. Aucun rôle runtime/maintenance n'a SUPERUSER/BYPASSRLS ni accès au migrateur. Le laboratoire utilise des données synthétiques et `trust` exclusivement local, sans constituer un modèle d'authentification opérationnelle.
- **J4.3B** : orchestration distribuée, cohérence Shop+Online, identité Auth réelle, inventaire distant, backups/PITR et rollback compatible restent non validés. Les bloqueurs de l'ADR et du rapport J4.3A subsistent. Aucun GO de migration physique n'est donné.

La politique restrictive et les limites MVCC ont été vérifiées contre la documentation primaire PostgreSQL 18 : [CREATE POLICY](https://www.postgresql.org/docs/18/sql-createpolicy.html), [isolation transactionnelle et séquences](https://www.postgresql.org/docs/18/transaction-iso.html).

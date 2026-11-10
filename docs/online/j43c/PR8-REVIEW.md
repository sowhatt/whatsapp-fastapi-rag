# Revue PR #8 — décision indépendante de la migration

Revue locale du 2026-11-10, [PR #8](https://github.com/sowhatt/whatsapp-fastapi-rag/pull/8). GitHub lu uniquement : OPEN, draft=true, merged=false, mergeable=true, head `d1e5dfa45d9678f792b199e68444347c7a79b6b5`, base `e34ea2f0d9c5f3270129e4b163e373f701f84520` sur `feat/whatzabi-online-j4-1-auth-v2-adapter`. Aucun thread de revue retourné par le connecteur ; ceci ne remplace pas une approbation humaine.

Branche locale initiale correcte et worktree Online propre. Commits examinés : `f8256fe` (fondations), `56b866a` (architecture/preuves), `d1e5dfa` (durcissement inbox/snapshots). La liste GitHub et le diff local contiennent exactement les mêmes 39 fichiers. Le parent Shop contient des travaux concurrents ; inventaire et empreintes conservés, aucune édition de ce worktree.

**GO technique pour fusion de la PR #8 à d1e5dfa dans son périmètre de fondations locales.** Ce verdict ne fusionne rien, ne publie pas J4.3C et n'autorise aucune migration. Les ajouts J4.3C locaux ne font pas partie de ce verdict sur le head distant.

**NO-GO migration Railway / J4.3B.** Le runtime historique n'est pas prêt pour les ACL minimales et la cohérence globale Shop–Online n'est pas assurée par le code existant.

## Revue des 39 fichiers

Les fichiers générés sont vérifiés par structure, compteurs et empreintes, les sources par lecture et recette. La liste SHA-256 complète figure dans `evidence/pr8_files.json`.

| Fichier | Conclusion de revue |
| --- | --- |
| `app/domains/core/contracts/__init__.py` | Paquet préparatoire sans import runtime ni effet. |
| `app/domains/core/contracts/commands.py` | Brouillon v1 typé ; pas de shop_id ni transport ; ne suffit pas à une bascule. v2 isolée en J4.3C. |
| `docs/online/j43a/ADR-001-PHYSICAL-SEPARATION.md` | Décisions D1–D6 proposées, non activées ; frontière labo et absence de garantie globale explicites. |
| `docs/online/j43a/CORE_CONTRACT.md` | Contrat v1 préparatoire, timeout ambigu et retry explicités ; boutique/transport à compléter. |
| `docs/online/j43a/REPORT.md` | Rapport historique : preuves cohérentes et migration explicitement NO-GO ; périmètre local conservé. |
| `docs/online/j43a/SECURITY_AND_RUNBOOK.md` | Rôles, limites GUC, rétention et rollback documentés ; aucune purge opérationnelle autorisée. |
| `docs/online/j43a/TABLE_MATRIX.md` | Tables, writers et dépendances FK inventoriés ; cible Core/Shop distincte de la source réelle. |
| `docs/online/j43a/evidence/git_inventory.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a/evidence/pytest.txt` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a/evidence/pytest.xml` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a/evidence/run.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a/evidence/validation_manifest.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a/external_schema_inventory.json` | Inventaire externe committé ; utile pour shop_inventories/Auth, sans import ni écriture. |
| `docs/online/j43a/orm_inventory.json` | Inventaire 34 tables ORM ; ne prétend pas refléter la base distante. |
| `docs/online/j43a1/REPORT.md` | Rapport historique : preuves cohérentes et migration explicitement NO-GO ; périmètre local conservé. |
| `docs/online/j43a1/STARTUP_SEPARATION.md` | DDL startup encore actif ; plan explicite et bloqueur de mise en service, aucun faux GO runtime. |
| `docs/online/j43a1/evidence/git_inventory.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a1/evidence/non_regression.txt` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a1/evidence/pytest.txt` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a1/evidence/pytest.xml` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a1/evidence/run.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `docs/online/j43a1/evidence/validation_manifest.json` | Artefact historique inspecté ; compteurs/empreintes vérifiés. Nouvelle recette dans pr8_regression, aucun résultat historique présenté comme nouvelle exécution. |
| `migrations/j43a_lab/001_baseline.sql` | Baseline ORM vide ; FK locales historiques ; jamais un upgrade de base existante. |
| `migrations/j43a_lab/002_receipts.sql` | PK tenant/source/clé et empreinte ; primitives préparatoires. |
| `migrations/j43a_lab/003_security.sql` | ENABLE/FORCE RLS ; absence de bypass ; privilèges runtime explicites. Droits inbox initiaux retirés par 005. |
| `migrations/j43a_lab/004_tenant_references.sql` | FK composites et quantités positives ; enfants Shop fermés. FK interdomaines à retirer dans une extraction future. |
| `migrations/j43a_lab/005_inbox_retention.sql` | Inbox append-only runtime, horodatage serveur, DELETE maintenance sous policy restrictive tenant ET âge. |
| `migrations/j43a_lab/README.md` | Périmètre laboratoire et ordre 001–005 explicitement indiqués. |
| `scripts/j43a/__init__.py` | Paquet scripts ; aucun démarrage de service. |
| `scripts/j43a/inventory.py` | Inventaire ORM sans connexion DB ni startup ; couverture externe séparée. |
| `scripts/j43a/lab.py` | Conteneurs possédés, daemon local, image fixée, migration atomique SHA/verrou, restauration cible distincte, snapshot cohérent. |
| `scripts/j43a/pytest_guard.py` | Refus egress sockets Python non loopback et refus skips ; pas un firewall général pour libpq/subprocess. |
| `scripts/j43a/receipts.py` | Savepoint autour effet/reçu/outbox ; déduplication/conflit ; reste une primitive locale sans saga. |
| `scripts/j43a/reconcile_readonly.sql` | REPEATABLE READ READ ONLY ; visibilité bornée par RLS ; pas de réparation. |
| `scripts/j43a/run.py` | Deux instances jetables, env filtré, 18.6 obligatoire, preuve de restauration et suite complète. |
| `scripts/j43a/verify_readonly.sql` | Snapshot lecture seule ; ACL tables/colonnes, membres/rôles/policies inspectés. |
| `tests/test_online_j42_postgres.py` | Diff limité au mode 18.6 obligatoire ; ancien mode 16 préservé ; rôles non propriétaires. |
| `tests/test_online_j43a_contracts.py` | Sept contrats et validation ; pas une preuve de transport ou de boutique. |
| `tests/test_online_j43a_postgres.py` | Refus ACL/RLS, rétention, snapshots concurrents, reçus, restauration ; 61 cas PG au total avec J4.2. |

## Constats P0/P1/P2

| Sévérité / portée | Constat confirmé | Décision |
| --- | --- | --- |
| P0 si activation distribuée | Shop écrit le stock tandis qu'Online conserve les consommations sans décrément physique partagé. Aucune autorité unique dans les parcours existants. | Bloque la bascule, pas la fusion de scripts isolés. Plan Shop arrêté avant modification. |
| P1 mise en service | Startup Online exécute DDL ; anciens installateurs contiennent des policies permissives/bypass. | Ne jamais les lancer sur le schéma sécurisé. Séparer migrateur/runtime et tester le lifespan complet de l'application réelle. |
| P1 séparation | FK transactionnelles entre Core et Online, v1 sans boutique, aucune saga réelle dans la PR. | Le prototype v2 J4.3C apporte une preuve locale distincte ; aucun changement de DSN opérationnel autorisé. |
| P1 exploitation | Identité Auth réelle, inventaire déployé, backup/PITR, mapping boutique et rollback applicatif compatible non validés. | NO-GO Railway/J4.3B. |
| P2 rétention | Purge inbox à 90 jours possible pour le rôle maintenance mais horizon de replay/PITR non approuvé. | Aucun job de purge ; conserver les reçus tant que les horizons ne sont pas définis. |
| P2 périmètre sécurité | GUC tenant choisissable par le détenteur des credentials SQL ; trust local et garde Python ne constituent pas une sécurité réseau de production. | Documenté ; identité/credentials serveur, ACL et RLS réelles testées. |
| P2 qualité | 5629 warnings historiques ; marqueur J4.3A et noms de rôles de laboratoire. | Dette documentée, aucune suppression de tests ni warning transformé en succès. |

Aucun P0/P1 bloquant **la fusion des seules fondations locales de cette PR** n'a été reproduit. Les défauts inbox mutables/antidatage et snapshots incohérents sont corrigés par 005 et les transactions read-only ; les tests négatifs/replays/restauration ont été rejoués. Les droits initiaux de 003 ne sont sûrs qu'après application de toute la série 001–005, atomique dans le lanceur.

## Recette réellement rejouée

`../.venv/bin/python -B -m scripts.j43a.run --report-dir docs/online/j43c/evidence/pr8_regression`

Résultat : **929 passed, 0 failure/error/skip**, **61 tests PostgreSQL 18.6**, 5629 warnings. Deux instances jetables distinctes, restauration et rétention retestées, conteneurs supprimés. Voir `evidence/pr8_regression/run.json`, `pytest.txt` et `pytest.xml`. Les manifests historiques J4.3A/J4.3A.1 n'ont aucune divergence d'empreinte (`evidence/pr8_artifact_verification.json`). Aucun résultat de base pilote ni distant n'est revendiqué.

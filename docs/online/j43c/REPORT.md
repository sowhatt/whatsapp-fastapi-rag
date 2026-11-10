# J4.3C — Livraison locale et décisions

Date : 2026-11-10. Base : `d1e5dfa45d9678f792b199e68444347c7a79b6b5`. Branche : `feat/whatzabi-online-j4-3a-db-isolation`. Commit local d'implémentation : **`5f4f16c`**.

**GO PR #8 à d1e5dfa**, pour ses fondations locales uniquement. **GO J4.3C pour les contrats et le prototype isolé validé. NO-GO J4.3B et migration Railway.** Les applications complètes Shop/Core/Online ne sont pas prêtes à être séparées physiquement. La PR n'a pas été fusionnée ou mise à jour ; aucun push n'a été réalisé.

## Livraison

| Livrable | Emplacement |
| --- | --- |
| Revue des 39 fichiers, migrations, RLS, privilèges et verdict PR | [PR8-REVIEW.md](PR8-REVIEW.md), [inventaire SHA-256](evidence/pr8_files.json) |
| Autorité du stock et transition sans doubles writes | [ADR-002-STOCK-AUTHORITY.md](ADR-002-STOCK-AUTHORITY.md) |
| Sept interfaces versionnées, préconditions, idempotence, erreurs/retry | [CONTRACTS-V2.md](CONTRACTS-V2.md), [JSON Schema v2](contracts-v2.schema.json), `scripts/j43c/contracts.py` |
| Diagramme des transactions et machines à états | [ORCHESTRATION.md](ORCHESTRATION.md) |
| Matrice des writers et stratégie offline Shop | [WRITERS-AND-OFFLINE.md](WRITERS-AND-OFFLINE.md) |
| Implémentation Core/FastAPI, saga, transport, signatures, simulateur Shop/PSP | `scripts/j43c/` ; aucun import dans `app/` |
| Laboratoire trois instances, rôles runtime, schémas avec RLS | `scripts/j43c/lab.py`, `core.sql`, `client.sql`, `run.py` |
| Tests et preuves finales | [recette J4.3C](evidence/lab/pytest.txt), [JUnit](evidence/lab/pytest.xml), [identités PostgreSQL et empreintes](evidence/lab/run.json) |

Le prototype est ajouté dans `scripts/j43c` plutôt que branché dans les routes existantes. Les migrations J4.3A et le brouillon de contrat v1 restent immuables. Les nouvelles bases ne contiennent pas de copie du schéma des pilotes ; elles sont vides puis peuplées de fixtures synthétiques.

## Tests réellement exécutés

```sh
../.venv/bin/python -B -m scripts.j43a.run --report-dir docs/online/j43c/evidence/pr8_regression
../.venv/bin/python -B -m scripts.j43c.run --report-dir docs/online/j43c/evidence/lab
node tests/merchant_j41_sw_test.cjs
git diff --check
```

- Régression PR #8 : **929 passed**, dont **61 tests PostgreSQL 18.6**, zéro échec/erreur/skip. Les 5629 warnings historiques restent présents.
- Recette distribuée finale : **64 passed**, zéro échec/erreur/skip, durée pytest **20,20 s**, lanceur complet **25,02 s**. Un warning de dépréciation Starlette/TestClient est conservé.
- Test Node : cache, exclusion API, offline et liens Push **PASS**.
- Vérification des espaces/diff : **PASS**. Les checksums des artefacts historiques J4.3A/J4.3A.1 concordent.

Total des deux recettes Python : **993 tests réussis**. Les deux suites ont été exécutées séparément ; les 64 nouveaux scénarios ne sont pas inclus artificiellement dans les 929 historiques. Les premiers passages du prototype ont permis de corriger la casse des headers signés et une requête d'inspection des ACL ; les preuves conservées sont celles du dernier code testé. Aucun test n'est ignoré ou remplacé par SQLite dans le laboratoire distribué.

| Exigence | Scénarios exécutés (`scripts/j43c/test_distributed.py`) |
| --- | --- |
| Shop et Online simultanés | `test_shop_online_simultaneous_full_sales` : trois bases, deux ventes/paiements, une seule consommation de la dernière unité, remboursement du perdant. |
| Dernière unité / réservations concurrentes | `test_last_unit_concurrent_reservations_no_oversell` (Online/Online et Online/Shop). |
| Ensemble multi-produits tout ou rien | `test_multi_line_failure_rolls_back_every_product`. |
| Timeout après commit | `test_core_atomicity_and_timeout_after_commit_replay`, `test_retry_after_timeout_keeps_exact_key_and_payload`, **`test_real_loopback_http_timeout_after_commit`** avec Uvicorn/requests. |
| Crash avant/après outbox et émission | `test_client_outbox_crash_and_restart`, `test_core_outbox_publish_crash_duplicate_delivery`, `test_create_order_and_outbox_are_atomic`. |
| Arrêt réel / reprise | `test_real_process_death_and_recovery` : `os._exit(91)` avant outbox, avant commit et après commit, puis reconstruction de l'orchestrateur depuis les bases. |
| Doublons commande / événement | `test_duplicate_command_concurrent_and_payload_conflict`, `test_concurrent_duplicate_event_delivery`, `test_inbox_effect_rollback_conflict_and_old_event`. |
| Événements hors ordre | `test_out_of_order_core_results_do_not_regress_projection` ; état Core récent conservé, résolution de la commande en attente. |
| Annulation pendant paiement | `test_payment_cancel_concurrently`, `test_cancel_during_ambiguous_reserve_then_late_payment_refund`. |
| Annulation après consommation ambiguë | `test_cancel_after_ambiguous_consume_compensates_once`, `test_release_consume_race_has_one_transition`. |
| Expiration | `test_expiration_after_payment_compensation_and_scheduler`, `test_expiration_is_checked_after_waiting_for_inventory_lock`. |
| Compensation / perte d'ACK remboursement | Tests d'annulation ci-dessus : mouvement inverse unique, refund_outbox et reçu PSP distinct durable. |
| Tenant A/B, boutique A/B | `test_tenant_and_shop_isolation_http_rls`, `test_scope_cleared_after_commit_rollback_and_sql_error`. |
| Signatures / source / terminal / montants | `test_service_signature_refusals`, `test_payment_amount_signature_and_duplicate_checks`, refus de terminal offline et de cible réseau non locale. |
| Offline puis synchronisation | `test_offline_preallocated_shop_sale_and_repeated_sync`, `test_offline_without_confirmed_allocation_is_rejected`. |
| Absence de double consommation | `test_record_sale_consumes_once_even_after_consume`, `test_record_sale_can_atomically_consume_confirmed_reservation`, mouvements uniques et replay des parcours complets. |
| ACL / RLS / rôles réels | Attributs et memberships, refus DDL/TEMP/TRUNCATE/SET ROLE, schéma Core absent d'Online, inbox/reçus/mouvements immuables, payload worker protégé. |

## Preuve PostgreSQL physique

Image officielle fixée : `postgres:18.6@sha256:979bccfde35445db618c65107d27d08c6c21339d8dc3ad4c830c6633947be0e4`.

| Instance de la dernière recette | `system_identifier` PostgreSQL | Version |
| --- | --- | --- |
| Core | `7706349209089830963` | `180006` |
| Online | `7706349214559100979` | `180006` |
| Shop simulé / faux PSP | `7706349218887704621` | `180006` |

Il s'agit de trois clusters/containeurs distincts, chacun avec son répertoire de données jetable ; pas trois schémas d'une même base. IDs des conteneurs, ports loopback, flags rôles, propriétaires et flags ENABLE/FORCE RLS sont conservés dans `evidence/lab/run.json`. Le faux PSP partage la troisième instance avec le simulateur Shop, mais a sa table et son login propres ; il n'est pas présenté comme un quatrième service physiquement isolé.

Rôles exercés : `j43c_core_runtime`, `j43c_core_worker`, `j43c_online_runtime`, `j43c_online_worker`, `j43c_shop_runtime`, `j43c_shop_worker`, `j43c_payment_runtime`. Tous sont NOSUPERUSER/NOBYPASSRLS/NOCREATEDB/NOCREATEROLE/NOREPLICATION, non propriétaires et sans membership migrateur/owner. L'administrateur jetable sert uniquement au bootstrap et à la lecture de la preuve physique ; les effets métier et les tests ACL/RLS passent par les logins runtime. `j43c_owner` est NOLOGIN ; le migrateur est séparé.

Les trois instances et le réseau du run final ont été supprimés. La recette historique a également supprimé ses deux instances. Aucun service préexistant n'a été arrêté, aucun volume existant n'a été monté, aucun DSN opérationnel n'a été chargé.

## Limites et risques résiduels

| Niveau | Risque | Critère avant activation |
| --- | --- | --- |
| P0 activation | Autorités actuelles Shop/Online concurrentes, writers directs et listener Shop toujours présents. | Autorisation Shop distincte, adaptation de tous les writers, retrait effectif des anciens privilèges. **Partie arrêtée à son plan.** |
| P1 | Les applications complètes ne sont pas intégrées au prototype ; startup Online historique avec DDL, FK interdomaines et transactions communes. | Parcours complets de l'application réelle, lifespan, erreurs et workers avec rôles minimaux sur les bases séparées. |
| P1 | Auth réelle, TLS, rotation/révocation des clés et résolution des droits tenant/boutique non raccordés. | Intégration interservice approuvée préservant Auth V2, tests des identités réelles dans environnement autorisé. |
| P1 | PSP et paiement offline simulés ; aucun flux bancaire, caisse IndexedDB ou retour physique réel validé. | Sandbox PSP autorisé, preuve d'idempotence remboursement/capture et intégration caisse. |
| P1 | Offline limité à des allocations par vente/terminal préacquises ; aucun quota générique ni récupération de terminal perdu. | Règles métier d'escrow et procédures de récupération, rejet de vente sans allocation, tests multi-terminaux. |
| P1 | Mapping boutique et solde d'ouverture historiques non établis ; achats/corrections demandent d'autres commandes. | Réconciliation autorisée et commandes Core supplémentaires pour **tous** les writers. |
| P1 | Pas de preuve RPO/RTO, disque/hôte, PITR ou rollback réel compatible. | Recette opérationnelle distincte, restauration et rejeu après point de bascule avec exploitation. |
| P2 | Retry plafonné à 60 s mais pas de jitter/circuit breaker, alerte, UI de quarantaine ou ordonnanceur déployé. | Observabilité, débit, monitoring des opérations ambiguës et runbooks avant production. |
| P2 | Reçus conservés sans purge ; croissance à dimensionner. | Rétention au-delà des horizons replay/PITR/offline, plan de maintenance sans affaiblir la déduplication. |
| P2 | Identités SQL serveur de confiance et GUC modifiables par leur détenteur ; trust limité aux conteneurs locaux. | Gestion des credentials/réseau ; ne jamais livrer de credentials SQL aux clients. |
| P2 | Warnings de dépendances, tests de charge et disponibilité prolongée absents. | Dette technique et recette de charge séparées, sans assimiler le succès fonctionnel à un SLO. |

Les allocations ne sont pas expirées automatiquement hors ligne : c'est une condition de non-survente, mais cela peut immobiliser du stock tant que le terminal n'est pas rapproché. Un timeout ne déclenche jamais une restitution spéculative.

## Git et contraintes respectées

Modifications limitées à `scripts/j43c/` et `docs/online/j43c/`. Aucun changement de `app/`, Auth V2, Shop, migrations existantes, tests existants, Procfile ou configuration de déploiement. Le contrôle final du parent Shop retrouve les mêmes **125 fichiers modifiés/non suivis** et les mêmes empreintes qu'au départ (`evidence/concurrency_after.json`). Aucun reset, checkout du parent ou nettoyage de travaux concurrents.

GitHub a été consulté en lecture seule deux fois : PR #8 toujours ouverte en brouillon à `d1e5dfa`, non fusionnée. Aucune écriture distante, aucun déploiement Railway, aucun accès aux bases pilotes ni à `zucchini-kindness`. Les seules demandes d'escalade concernaient le moteur Docker **local** et l'écriture du Git partagé nécessaire aux commits locaux demandés.

## Verdicts séparés

| Décision | Verdict | Portée |
| --- | --- | --- |
| PR #8 | **GO technique à d1e5dfa** | Fondations locales revues, 929 tests rejoués ; ce n'est ni un merge exécuté ni un GO de mise en service. |
| J4.3C | **GO prototype local** | Contrats v2, saga durable, trois bases physiques synthétiques et 64 scénarios validés. |
| J4.3B | **NO-GO activation** | Intégration réelle, autorisation/adaptation writers Shop, identité/PSP et prérequis d'exploitation non clos. |
| Migration Railway | **NO-GO** | Aucun parcours complet déployable validé, aucune migration physique opérationnelle réalisée ou autorisée. |

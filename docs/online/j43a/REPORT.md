# J4.3A — Rapport de livraison locale et verdict

**Fondations locales livrées et vérifiées. NO-GO pour une séparation/bascule J4.3B.**
L'extraction physique et la réécriture des transactions sont arrêtées à la frontière de l'ADR, conformément à la consigne. Aucun blocage n'a été contourné en augmentant les droits ou en désactivant RLS.

Référence initiale : `e34ea2f0d9c5f3270129e4b163e373f701f84520`.
Branche locale : `feat/whatzabi-online-j4-3a-db-isolation`.
Commit des fondations/test : `f8256fe669d78ac83921b2301b03da0e4086e65d`.
Exécution de référence : **2026-10-29T15:56:33.382613+00:00**, durée totale 17.06 s.

## Livrables et portée

| Livrable | Résultat vérifiable |
| --- | --- |
| Matrice tables/PK/FK/domaines/RLS/rôles/flux | [TABLE_MATRIX.md](TABLE_MATRIX.md), [inventaire ORM](orm_inventory.json), [complément externe committé](external_schema_inventory.json) |
| ADR et architecture cible | [ADR-001-PHYSICAL-SEPARATION.md](ADR-001-PHYSICAL-SEPARATION.md), décisions D1–D6 à valider |
| Sept commandes Core | [CORE_CONTRACT.md](CORE_CONTRACT.md), `app/domains/core/contracts/commands.py` ; sans implémentation de transport |
| Migrations et rôles | Quatre migrations versionnées `migrations/j43a_lab/`, bootstrap contrôlé `scripts/j43a/lab.py` ; uniquement base locale vierge |
| Idempotence/outbox/inbox | `scripts/j43a/receipts.py` ; effets et reçus atomiques, conflits/duplication/retry testés localement |
| PostgreSQL 18.6 | `scripts/j43a/run.py`, `tests/test_online_j43a_postgres.py`, adaptation contrôlée de la fixture J4.2 ; version exacte 180006 |
| Sauvegarde/restauration et rollback | [SECURITY_AND_RUNBOOK.md](SECURITY_AND_RUNBOOK.md), restauration effectuée sur deuxième instance physique jetable |
| Preuves de recette | [run.json](evidence/run.json), [pytest.txt](evidence/pytest.txt), [JUnit](evidence/pytest.xml), [manifeste de validation](evidence/validation_manifest.json) |
| Git et travaux concurrents | [Inventaire Git](evidence/git_inventory.json) ; branche issue de la référence, deux commits locaux à la livraison |

## Résultats de recette

**913 passed ; 0 failed ; 0 errors ; 0 skipped.** Parmi eux : **45 tests PostgreSQL 18.6**, dont 13 régressions PG historiques J4.2/J4.2.1 et 32 cas de laboratoire/annulation supplémentaires ; 868 autres tests Python. Le lanceur fait échouer la recette en présence d'un skip.

| Vérification | Preuve / résultat |
| --- | --- |
| Installation depuis vide, replay et empreintes migrations | Tests du laboratoire ; les checksums enregistrés correspondent aux quatre fichiers committés ; empreinte altérée refusée |
| Droits minimaux, aucun runtime superuser/bypass/propriétaire | Vrais logins Core/Online/worker ; refus DDL, TEMP, SET ROLE, TRUNCATE, tables Shop, modification RLS ; droits outbox par colonne |
| RLS A/B et pool | Lecture/écriture étrangère refusée ; faux `app.rls_bypass` inopérant dans nouvelles policies ; contexte absent après commit, rollback, erreur SQL et retour au pool |
| Références tenant | Mise à jour d'une ligne de commande vers le produit d'un autre tenant refusée par FK composite |
| Checkout multi-articles et concurrence | Régressions PostgreSQL sur une autorité SQL locale ; deux checkouts concurrents, consommation concurrente idempotente, expiration pendant attente d'un verrou |
| Annulation / expiration | Annulation après confirmation libère une seule fois, Core/Online concordent, stock physique inchangé ; régressions d'expiration/revalidation |
| J4.2.1 et `autoflush=False` | Revalidation partiellement expirée à stock exact ; rollback après flush ; contexte réappliqué après erreur |
| Outbox et reçus | Une commande concurrente produit un seul effet/un seul événement ; rollback effet+reçu+outbox même si l'appelant intercepte l'exception et commit |
| Inbox | Livraison répétée sans double effet ; même ID/autre payload refusé ; erreur consommateur rollback le reçu |
| Restauration | Empreintes de toutes les lignes, séquences, contraintes, index, ACL tables/colonnes/effectives, policies, owners et memberships concordants ; nouvel accès applicatif testé sur cible restaurée |

Archive synthétique testée : **206687 octets**, SHA-256 `20ba6c47629019de0b12919f88d681cf450517f145403835e2e787aee599d4fe`. Elle a circulé en mémoire entre conteneurs puis a été détruite avec les ressources de test. C'est une preuve de procédure, **pas une sauvegarde staging disponible**.

Environnement : Python 3.12.13, pytest 9.1.1, SQLAlchemy 2.0.51, psycopg 3.3.4, psycopg2 2.9.13. Image et digest exacts dans `run.json`. Les deux conteneurs et leur réseau ont été supprimés après le run. Aucun service existant n'a été arrêté.

Le run affiche 5035 warnings. Leur détail est masqué par `--disable-warnings`, mais leur décompte est conservé dans la sortie ; ce sprint ne les traite pas comme des erreurs ni ne prétend les avoir corrigés. Les tests PostgreSQL n'ont pas été remplacés par SQLite. Les autres tests continuent d'utiliser leur environnement unitaire prévu.

## Limites qui empêchent le GO J4.3B

| Blocage | Critère de levée |
| --- | --- |
| Transaction Core–Online actuellement mono-base | ADR D1/D2 validée ; orchestrateur durable implémenté et testé sur deux bases réelles avec crash/timeout/rejeux ; aucun commit distant supposé atomique |
| Stock Shop écrit directement, consommation Online distincte | D3/D4 validées ; inventaire de tous les writers et du scope boutique, correspondance des produits, adaptateur Shop explicitement autorisé ; preuve de non-survente **globale** |
| Runtime actuel incompatible avec rôle minimal | Suppression du DDL startup au profit du migrateur ; résolution tenant et lectures publiques adaptées ; aucune augmentation opportuniste de droits |
| Auth V2 développé séparément | Contrat d'identité réel et accès administrateur attestés dans son chantier ; aucun modèle/secret Auth copié ici |
| Inventaire réel et historique à réconcilier | Audit autorisé du catalogue déployé comparé aux références, données anormales examinées et décisions de traitement approuvées ; aucune donnée distante modifiée par ce sprint |
| Rollback dédié et backup opérationnel non attestés | Image antérieure compatible avec base dédiée, backup/PITR source autorisé, restauration réelle isolée et RPO/RTO mesurés ; e34ea2f seul n'est pas un rollback après séparation |

Les tests ne prouvent pas un checkout distribué ni la non-survente Shop+Online simultanée. La deuxième instance de test sert à la restauration. L'absence de ces implémentations découle de l'arrêt demandé sur décision d'architecture non validée ; ce ne sont pas des tests obligatoires masqués par `skip`.

La matrice couvre exhaustivement les 34 tables ORM de la référence Online, ajoute la table analytique et six vues SQL, puis les objets externes committés connus. La présence effective de ces objets sur Railway et les évolutions Shop non committées ne peuvent pas être déduites de cette cartographie locale. Elles restent une entrée obligatoire de l'audit J4.3B.

## Sécurisation Git et contraintes respectées

Le worktree Online était propre à e34ea2f au départ. Toutes les branches/worktrees connus et les références distantes ont été lus ; la branche demandée a été créée depuis ce commit. Le worktree Shop parent contient des changements concurrentiels nombreux, et le worktree historique temporaire est prunable : aucun de ces travaux n'a été modifié, réinitialisé ou nettoyé. La source Auth externe est seulement lue à son commit ; ses fichiers non committés ne sont pas intégrés.

Le diff applicatif est limité à l'ajout de contrats non raccordés. Aucun chemin `app/main.py`, `app/models`, `app/routers`, `app/services`, `app/db`, `app/merchant`, `app/shared` existant n'est modifié. Aucun push, merge, déploiement, appel Railway ou connexion à une base distante pendant J4.3A. Aucune migration physique réelle, aucune intervention sur Shop/production/Auth, aucune valeur sensible affichée.

## Retour arrière et suite

Le [runbook](SECURITY_AND_RUNBOOK.md) fixe les étapes d'approbation, de réconciliation, de sauvegarde, de provisionnement, de coupure, de recette et de retour. Tant que l'ADR n'est pas validée, conserver la référence opérationnelle actuelle et les protections existantes. Ne pas utiliser les migrations du laboratoire contre staging.

Après une future bascule avec nouvelles écritures, revenir à l'ancienne base partagée ferait perdre la cohérence. Le rollback doit conserver la base dédiée et Core comme autorité, utiliser un binaire compatible, ou restaurer sur une nouvelle instance dédiée puis rapprocher/rejouer les opérations prouvées. Ne jamais restaurer Shop pour corriger Online.

**Décision : GO pour revue des fondations locales ; NO-GO pour exécution J4.3B tant que les critères ci-dessus ne sont pas levés et l'étape suivante explicitement autorisée.**

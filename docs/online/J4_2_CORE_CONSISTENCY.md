# J4.2 — Cohérence Core–Online, réservations et RLS

## Livraison locale

Base vérifiée après `git fetch origin` :
`662ef67327af9b047ebcf90f848f19a2e5b89e53`,
branche J4.1B `feat/whatzabi-online-j4-1-auth-v2-adapter`.
HEAD local et référence distante concordaient ; répertoire de travail propre.
La nouvelle branche est `feat/whatzabi-online-j4-2-core-consistency`.
Les autres worktrees ont uniquement été identifiés par `git worktree list`.

Ce sprint corrige les anomalies du rapport de reprise ; il ne réalise pas
les modules Commerce initialement envisagés sous le nom J4.2 dans la roadmap J4.1.
Aucun changement Auth V2, workflow Shop, transport Push, Delivery ou contrat
d'événement. Aucun push, merge, déploiement ou accès à une base staging/production.
Aucune migration nécessaire.

## Cohérence transactionnelle

`app/domains/core/public/transactions.py` expose
`update_commerce_transaction`, utilisé par les commandes Online de statut et
de paiement. La recherche verrouille la racine Core, filtre son identifiant,
son marchand et son type `commerce`. Une racine absente, étrangère ou d'un autre
type entraîne un refus ; le paiement ne peut plus ignorer silencieusement
l'absence de transaction Core.

| État Online | État Core |
|---|---|
| pending | pending |
| confirmed | confirmed |
| preparing | confirmed |
| ready | confirmed |
| completed | completed |
| cancelled | cancelled |

La préparation et la disponibilité sont des détails Online. Core conserve
ses états partagés existants. Une ancienne racine `pending` peut être remise
en cohérence lors d'une commande valide sur son agrégat Online ; une racine
terminale contradictoire ne peut pas régresser.

La commande publique Core ne commit jamais. Les commandes Online possèdent
la transaction locale : commande, racine Core, réservations et événements
outbox réussissent ou sont annulés ensemble. Le décorateur `tenant_mutation`
annule la transaction sur exception, y compris si un appelant tente ensuite
de commit. Les lectures de réponse après commit reçoivent à nouveau le
contexte RLS.

Les demandes répétées de l'état courant n'émettent pas de nouvel événement.
Pour une commande terminée, le rejeu vérifie aussi l'ensemble consommé.
Un rejeu de confirmation avec stock devenu invalide reste refusé.
Un ancien état demandé après progression vers un autre état reste une
transition invalide : il n'existe pas de journal générique de clés d'idempotence.
Le paiement identique est également rejouable sans double `payment.received`.

L'import direct de `BusinessTransaction` est supprimé du service de paiement.
La création de transaction au checkout et certaines lectures de réservations
conservent leurs imports existants ; leur extraction complète n'est pas
nécessaire aux corrections de ce sprint.

## Réservations complètes et concurrence

`check_reservation_set` est une commande publique Core sans commit :

- verrou de la commande Online acquis par l'appelant ;
- verrouillage des produits par identifiant croissant, puis des réservations ;
- évaluation de l'heure après acquisition des verrous ;
- égalité exacte des quantités agrégées par produit avec les lignes de commande ;
- refus des articles manquants, surnuméraires, quantités invalides, états
  consommés prématurément et réservations actives expirées ;
- consommation ou prolongation du même ensemble verrouillé, sans seconde
  sélection temporelle susceptible de ne traiter qu'une partie des lignes.

Les anciennes lignes libérées/expirées sont conservées pour l'historique.
Elles ne satisfont pas une réservation actuelle. Les lignes consommées
satisfont uniquement un rejeu déjà terminé ; leur ancienne date d'expiration
ne les remet pas en disponibilité.

La revalidation vérifie les quantités, pas seulement le nombre de lignes.
Elle reconstruit un ensemble partiel et refuse une commande contenant déjà
des lignes consommées. Le nettoyage d'expiration verrouille et recharge les
lignes pour ne pas écraser un état concurrent déjà modifié.

Le stock physique `Product.stock` et les workflows Shop restent inchangés.
La règle existante demeure : les réservations consommées réduisent la
disponibilité Online. La synchronisation future du stock physique Shop/Core
n'est pas ajoutée implicitement.

Les lignes de commande restent des snapshots immuables dans les API existantes.
Toute future mutation de ces lignes devra respecter le verrou de commande.

## Isolation RLS

Le contexte `apply_rls_context(..., merchant_id=...)` est établi dans les
services de mutation, avant toute requête, y compris pour leurs appelants
administratifs :

- statut de commande ;
- statut de paiement ;
- revalidation de stock ;
- nettoyage des réservations expirées.

Les filtres SQL explicites sur le marchand sont maintenus. Aucun nouveau
bypass n'est introduit ; les commandes imposent `app.rls_bypass=false`.
Le contexte est réappliqué après commit pour les lectures de réponse, et
après rollback avant le nettoyage d'expiration existant de la revalidation.

Les politiques RLS installées sur `business_transactions` et `outbox_events`
ne sont pas changées. Les tables Online encore protégées uniquement par
filtrage applicatif ne reçoivent pas de politique improvisée.

Le compte global du cockpit technique conserve son contrat d'autorisation.
Le tenant de la Merchant PWA reste issu du resolver serveur existant.
Auth V2 n'est pas raccordé par ce sprint.

## Worker

Sans `--send`, `_run_once` ne lance ni récupération, ni matérialisation,
ni commit. Les événements `processing` expirés restent strictement inchangés.
Le rapport retourne `recovered=0`.

Avec `--send`, `merchant_id` et `event_id` sont transmis identiquement à la
récupération et à la matérialisation. La récupération reste limitée à
`notification.requested` et verrouille les lignes avec `SKIP LOCKED`.
Les paramètres ajoutés au helper partagé sont optionnels ; les appelants
existants gardent leur périmètre par défaut. Le transport historique n'est
pas modifié.

Le contexte privilégié préexistant du worker global est conservé, sans
extension aux commandes métier. Le dry-run peut établir ce contexte SQL
transactionnel pour lire ; il ne modifie aucune donnée persistante.

## Tests et résultats exécutés

Virtualenv utilisé :
`/Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python`.

Tous les appels pytest utilisent `DATABASE_URL=sqlite://`,
`PYTHONDONTWRITEBYTECODE=1`, `-B`, `-p no:cacheprovider`,
`-q --disable-warnings`. Les suites finales incluent aussi `--tb=short`.

| Validation | Résultat |
|---|---|
| Baseline dépôt avant modification | 823 passed, 1952 warnings, 6.53 s |
| Ciblés Core/stock/worker + régressions lifecycle/paiement/outbox | 69 passed, 2025 warnings, 1.69 s |
| PostgreSQL 16 isolé, après ajout de tous ses cas | 9 passed, 633 warnings, 3.03 s |
| Online + fondations, PostgreSQL activé | 381 passed, 3680 warnings, 8.62 s |
| Dépôt complet, PostgreSQL activé | 867 passed, 3840 warnings, 10.09 s |
| `python -m compileall -q app` | exit 0 |
| `git diff --check` | exit 0 |

Les 44 nouveaux cas sont répartis entre :

- `tests/test_online_j42_core_consistency.py` : mapping, rejeux, annulation,
  échec outbox après flush et refus d'une racine étrangère ;
- `tests/test_online_j42_reservation_integrity.py` : checkout réel à deux
  articles, neuf défauts testés à confirmation et finalisation, rejeu consommé,
  revalidation des quantités et refus de reconstruire sur du consommé ;
- `tests/test_online_j42_worker_dry_run.py` : snapshot intégral inchangé,
  absence de SQL DML/commit, filtres marchand/événement et transmission aux helpers ;
- `tests/test_online_j42_postgres.py` : neuf intégrations réelles PostgreSQL.

La suite Online exécutée comprend `tests/test_online*.py` et :
`test_stock_reservation.py`, `test_transactional_outbox.py`,
`test_rls_foundation.py`, `test_s0_rls_scope.py`, `test_outbox_rls_scope.py`,
`test_business_transaction_abstraction.py`. Elle conserve les tests J4.1,
J3, Web Push et SSRF.

Les avertissements pytest sont comptabilisés, sans être présentés comme corrigés.

## Reproduire PostgreSQL 16 sans base partagée

Démarrer un conteneur jetable avec port dynamique lié uniquement à localhost :

```sh
docker run --detach --rm --name whatzabi-j42-pg16 \
  --label whatzabi.task=j42 --publish 127.0.0.1::5432 \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_DB=whatzabi_j42_test postgres:16
docker port whatzabi-j42-pg16 5432
```

L'authentification locale sans mot de passe est réservée à ce conteneur
de tests jetable, sans donnée réelle ; ce n'est pas une configuration runtime.
Reporter le port affiché dans la commande suivante :

```sh
PYTHONDONTWRITEBYTECODE=1 DATABASE_URL=sqlite:// \
WHATZABI_J42_PG_PORT=<port-local> \
/Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -B -m pytest \
  -p no:cacheprovider tests/test_online_j42_postgres.py \
  -q --disable-warnings --tb=short
docker stop whatzabi-j42-pg16
```

Les tests acceptent uniquement `127.0.0.1`, la base `whatzabi_j42_test`
et PostgreSQL majeur 16. Ils ne lisent aucune URL de staging.
Chaque cas crée un schéma et un rôle LOGIN non propriétaire, `NOSUPERUSER`
et `NOBYPASSRLS`, puis les supprime dans un `finally`.
Le superutilisateur local sert uniquement à installer et supprimer le
périmètre jetable ; les scénarios métier, checkout compris, s'exécutent
sous le rôle restreint.

Les neuf cas couvrent :

1. Routes administratives de statut/paiement et cohérence Core.
2. SELECT/UPDATE/INSERT inter-tenants refusés par RLS ; contexte effacé au
   commit, au rollback et lors de la réutilisation d'une connexion.
3. Lecture et mutations d'une commande B avec le tenant A refusées.
4. Deux finalisations simultanées avec ORM préchargé : un événement, deux
   lignes consommées une seule fois.
5. Expiration d'une ligne pendant l'attente du verrou produit.
6. Deux checkouts multi-articles simultanés : un gagnant, aucune survente.
7. Refus de finalisation avec une ligne expirée sans écriture partielle.
8. Échec injecté après flush pendant finalisation : rollback Core/stock/outbox.
9. Échec de revalidation, nettoyage et reprise avec contexte tenant correct.

Sans `WHATZABI_J42_PG_PORT`, ces neuf tests sont explicitement skipped.
Ils étaient activés et passants dans les deux suites finales rapportées.
Le serveur exécuté était PostgreSQL **16.15**. La vérification finale a trouvé
zéro schéma `j42_%` et zéro rôle `j42_%` résiduels, puis le conteneur a été
arrêté et supprimé par son option `--rm`.

## Risques résiduels et décision

GO pour livraison locale et revue J4.2 sur le périmètre de corrections.
Ce verdict n'autorise aucun déploiement.

- Les données historiques incohérentes ne sont pas réparées en masse.
  Une procédure dédiée de diagnostic/réconciliation devra être revue avant
  toute intervention staging/production. Une commande valide ou un rejeu
  contrôlé peut rattraper une racine Core `pending`.
- L'intégration Auth V2 reste bloquée comme documenté en J4.1B :
  aucune session simulée ou dérogation n'est ajoutée.
- La validation PostgreSQL utilise les modèles et installateurs du dépôt,
  sans prétendre vérifier le schéma réel d'une base déployée.
- L'isolation DB des tables Online sans politiques reste une étape future ;
  les filtres applicatifs et les tests A/B restent nécessaires.
- L'extraction de tous les imports internes Core, les modules Commerce,
  Mobile Money réel et Delivery complet restent hors périmètre.
- Les tests de concurrence couvrent des courses déterministes ciblées,
  pas une campagne de charge ni toutes les combinaisons de panne.

Fichiers applicatifs concernés : `app/domains/core/public/transactions.py`,
`app/domains/core/public/stock.py`, `app/domains/online/internal/mutation.py`,
`app/domains/online/internal/order_service.py`,
`app/domains/online/internal/payment_service.py`, `app/online_outbox_worker.py`,
`app/shared/outbox/worker.py`. Les quatre fichiers de tests ci-dessus et
ce document complètent la livraison.

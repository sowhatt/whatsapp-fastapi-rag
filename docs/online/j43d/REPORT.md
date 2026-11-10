# WHATZABI J4.3D — Livraison locale

10 novembre 2026. Base Online `aeacb36ee4571d8046118fa8da955b63185a99b6` ; Shop audité en lecture seule à `71d05821b3e02c678dff76266db25885db753c33`, avec ses travaux non committés préservés.

Branche locale : `feat/whatzabi-online-j4-3d-shop-core`. Commit d'implémentation et tests : **`f538161`**. Les preuves ont été produites avant commit, à partir des mêmes octets de source, dont les SHA-256 sont enregistrés dans `evidence/lab/run.json`.

**GO pour la préparation et le laboratoire. NO-GO pour brancher ou activer les parcours Shop réels.** L'intégration nécessite de modifier leurs writers, le listener de stock et les transactions métier ; conformément à la mission, cette partie est arrêtée au plan avant toute écriture. Aucun verdict de non-survente des caisses pilotes n'est revendiqué.

## Livrables

| Livrable | Fichier |
| --- | --- |
| Matrice des writers réels, écarts Shop/Online et frontière d'intervention | [WRITERS.md](WRITERS.md) |
| Autorité par tenant/boutique/produit, architecture et plan de raccordement | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Étude quotas, reconnexion et terminaux perdus | [OFFLINE-QUOTAS.md](OFFLINE-QUOTAS.md) |
| Adaptateur préparatoire non branché, flag désactivé par défaut | `scripts/j43d/adapter.py` |
| Tests et lanceur isolé | `scripts/j43d/test_adapter.py`, `scripts/j43d/run.py` |
| Preuves physiques PostgreSQL, ACL, identités et empreintes de code | [lab/run.json](evidence/lab/run.json) |
| États de stock et équations de conservation vérifiées | [lab/invariants.jsonl](evidence/lab/invariants.jsonl) |
| Régression complète et recette distribuée | [regression/pytest.txt](evidence/regression/pytest.txt), [lab/pytest.txt](evidence/lab/pytest.txt), XML JUnit adjacents |
| Protection des travaux concurrents et d'Auth V2 | [sources_before.json](evidence/sources_before.json), [sources_after.json](evidence/sources_after.json) |
| Références PR vérifiées en lecture seule | [references.json](evidence/references.json) |

## Exécution et résultats

```sh
../.venv/bin/python -B -m scripts.j43d.run --report-dir docs/online/j43d/evidence/lab
../.venv/bin/python -B -m scripts.j43a.run --report-dir docs/online/j43d/evidence/regression
node tests/merchant_j41_sw_test.cjs
git diff --check
```

- **95 tests réussis**, zéro échec, erreur ou skip, en 32,08 s : les **64** scénarios J4.3C réexécutés et **31** nouveaux tests J4.3D (24 validations/gardes sans base et 7 scénarios avec bases physiques). Lanceur complet : 36,59 s. Un warning Starlette/TestClient historique.
- **929 tests de régression réussis**, zéro échec, erreur ou skip, en 19,40 s, dont **61 PostgreSQL**. Les autres tests historiques utilisent leur isolation habituelle, notamment SQLite ; ils ne sont pas présentés comme 929 tests distribués. 5629 warnings historiques.
- Total Python : **1024 réussis**, sans doubler les 64 tests J4.3C dans ce total. Service worker Node : **PASS**.
- Pas de chargement de `.env` ni de DSN opérationnel ; le lanceur n'accepte aucun DSN. L'environnement du sous-processus de tests est filtré et le garde réseau Python limite les connexions au local. Le socket Docker nécessitait une escalade du sandbox, obtenue uniquement pour les recettes locales.

| Scénario nouveau | Assertion / preuve |
| --- | --- |
| Flag absent/désactivé, même si une variable homonyme vaut true | Aucun client ni accès base/réseau construit ; `None` rend la main au futur appelant legacy. Aucune configuration réelle n'est changée. |
| Autorité CORE suspendue, FROZEN, inconnue, panier mixte | Refus avant I/O ; aucune retombée sur un writer legacy d'une clé CORE. |
| Mauvais tenant/boutique/terminal, quantités ou parcours non pris en charge | Refus explicites avant création d'intention Core. |
| 4 ventes Shop + 4 Online pour 3 unités | 3 ventes terminées, 5 refusées/remboursées, stock final 0, consommé 3. Rejeu des intentions Shop sans seconde consommation. |
| Retry durable et payload modifié | Même identifiant après reconstruction de l'adaptateur ; conflit si montant, quantité, mode offline ou terminal change. |
| Annulation après consommation et ACK perdu | État ambigu conservé ; un mouvement CONSUME et un RETURN seulement ; stock revenu à 1, remboursement unique. |
| Mort du processus Shop avant/après commit | Sous-processus arrêté via `os._exit(91)` ; intention et outbox toutes deux absentes ou présentes, puis reprise jusqu'à vente unique. |
| Deux terminaux préalloués, déconnectés puis reconnectés | Pendant coupure : physical=2, reserved=2, consumed=0 ; Online refusé. Après replay : physical=0, reserved=0, consumed=2. Nouveau sale_id sur la même allocation refusé. |
| Offline sans allocation ou sans ACK | Aucune vente acceptée, aucune consommation. |

Les 64 scénarios hérités complètent cette recette : dernière unité, multiligne atomique, véritables HTTP loopback et timeout après commit, mort du processus Core, retry stable, annulations concurrentes, événements dupliqués/hors ordre, expiration après verrou, RLS, permissions des workers et refus DDL/TEMP/TRUNCATE/SET ROLE. Ils testent le Core laboratoire, pas les routes métier réelles Shop.

## Trois bases indépendantes et identités restreintes

Image fixée : `postgres:18.6@sha256:979bccfde35445db618c65107d27d08c6c21339d8dc3ad4c830c6633947be0e4`.

| Service | `system_identifier` PostgreSQL | Version |
| --- | --- | --- |
| Core | `7706498786310156339` | 180006 |
| Online | `7706498790266322995` | 180006 |
| Shop synthétique et faux PSP | `7706498794441027632` | 180006 |

Trois conteneurs/clusters, données en mémoire jetables, ports loopback distincts. Les rôles **réellement utilisés** sont ceux de J4.3C : `j43c_core_runtime`, `j43c_core_worker`, `j43c_online_runtime`, `j43c_online_worker`, `j43c_shop_runtime`, `j43c_shop_worker`, `j43c_payment_runtime`. Tous sont NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION, sans membership owner/migrateur. Owner NOLOGIN et migrateur séparé ; FORCE RLS tenant/boutique. L'administrateur jetable sert au bootstrap et à la preuve d'identité, pas aux effets métier des tests.

Le faux PSP utilise une table et un login distincts dans la base Shop ; aucune indépendance physique d'un quatrième service n'est prétendue. Les clés HMAC et terminaux sont synthétiques. L'authentification PostgreSQL trust est limitée au laboratoire local ; les identités SQL démontrent les privilèges, pas un système de credentials de production.

Les trois instances de la recette et les deux instances de régression ont été nettoyées par leurs lanceurs. Aucun volume préexistant n'a été monté et aucun service préexistant n'a été arrêté.

## Risques résiduels et critères de GO d'intégration

| Priorité | Risque / limite actuelle | Condition avant activation |
| --- | --- | --- |
| P0 | Writers Shop, listener et writers Online historiques restent actifs et indépendants du prototype | Autorisation distincte ; adaptation complète de la matrice ; démonstration de retrait de l'autorité SQL historique pour chaque clé migrée. |
| P0 | Registre d'autorité seulement immuable en mémoire dans le laboratoire ; aucun epoch/fencing durable | Registre, frontière de transaction, watermark, drainage et refus d'un ancien binaire démontrés. Aucun rollback par simple flag. |
| P0 | Achats, annulations achat, comptages, réassorts et retours physiques absents du contrat v2 | Contrats supplémentaires et tests de concurrence avec réservations/quotas ; retour partiel/qualité et imports sans effet stock. |
| P1 | Saga non atomique avec les vraies `Sale`/lignes/dettes/paiements du Shop ; crédit et paiements partiels non intégrés | Intention + outbox dans la transaction métier, projections sans second décrément, tests des vrais parcours après autorisation. |
| P1 | Auth V2 préservée mais non raccordée ; identité terminal/clé, TLS et révocation simulés | Réutiliser les contrôles utilisateur, rôle et boutique historique ; résoudre les identités worker par terminal à partir de données de confiance. |
| P1 | Offline limité au séquestre par vente, PostgreSQL en guise de journal local ; pas de quotas réutilisables ni protection contre clonage | Journal IndexedDB atomique et protocole de clôture/reconnexion ; hypothèse de terminal unique et traitement des terminaux perdus explicites. |
| P1 | Annulation suppose des marchandises non remises ; remboursement PSP fictif | Preuve de garde/retour revendable et sandbox PSP autorisée. |
| P1 | Aucun rapprochement des données pilotes, d'identifiants ou des writers distants | Audit autorisé en environnement dédié, solde d'ouverture attesté et inventaire complet des versions déployées. |
| P2 | RLS suppose des services de confiance pouvant choisir leur GUC ; rôle Core permet son propre DML | Gestion des credentials et surface SQL, confinement réseau et permissions de commandes de production. |
| P2 | Pas de SLA, charge prolongée, panne disque/hôte, PITR ou test de restauration J4.3D ; rétention reçus non bornée | Recette opérationnelle, RPO/RTO, dimensionnement, observabilité et politique de rétention compatible avec offline/replay. |

## Restrictions et état final

Seuls `scripts/j43d/` et `docs/online/j43d/` sont ajoutés. Les 333 fichiers de sources Shop inventoriés et les 223 fichiers applicatifs Online contrôlés ont les mêmes empreintes avant/après ; aucun nouveau fichier source Shop détecté. Auth V2, les migrations et les prototypes antérieurs sont intacts. Les travaux concurrents ne sont ni nettoyés, ni réinitialisés, ni embarqués dans les commits.

Aucun accès à `zucchini-kindness`, aucune donnée pilote modifiée, aucun déploiement Railway, aucun push, merge ou message distant. Les seules lectures GitHub portent sur les PR de référence. Les valeurs de flag True sont uniquement des objets de test éphémères ; aucun feature flag applicatif activé.

**Verdict : GO préparation locale et poursuite de conception ; NO-GO intégration/activation/pilotes.** Les modifications nécessaires des vrais writers sont décrites dans le plan et n'ont pas été entreprises.

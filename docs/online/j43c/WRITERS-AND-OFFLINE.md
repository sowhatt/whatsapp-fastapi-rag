# Writers, stratégie Shop et frontière d'autorisation

Inventaire de sources locales au 2026-11-10. Online : `d1e5dfa`. Worktree Shop parent : `71d0582` sur `feat/s2-5-home-drilldowns`, avec modifications concurrentes non committées. Lecture seule de ces sources, sans les importer ni les exécuter. Les empreintes des fichiers modifiés sont conservées dans `evidence/concurrency_before.json`. Cet inventaire ne prétend pas connaître les versions ni les scripts effectivement exécutés sur Railway.

| Domaine / entrée | Writer observé | Données et comportement actuel | Cible / action requise |
| --- | --- | --- | --- |
| Shop contenu dans la référence Online : création produit | `app/routers/products.py:create_product`, `app/services/catalog_service.py:create_product` | Product.stock initial ; Product.initial_stock | Commande Core d'ouverture/ajustement à définir après autorisation Shop. |
| Shop référence Online : agent conversation | `app/agents/conversation_agent.py` | Création Product à stock 0 | Même mapping tenant/boutique obligatoire. |
| Shop référence Online : édition | `app/routers/products.py` (`setattr`), `catalog_service.py:update_product_stock`, `update_product_initial_stock` | Remplacement stock ou référence initiale | Ne plus autoriser de SET direct après bascule. Initial_stock reste une référence, pas une quantité disponible. |
| Shop référence Online : vente / annulation | `app/routers/sales.py` | Product.stock -= quantité / += quantité ; StockMovement | Réservation/consommation/vente et compensation Core ; retrait des writes locaux. |
| Shop référence Online : achat / annulation | `app/routers/purchases.py` | Product.stock += quantité / -= quantité ; StockMovement | Contrats Core d'entrée/inversion nécessaires ; hors des sept commandes de vente. |
| Shop parent : sélection de boutique | `../app/services/shop_context_service.py:_overlay_shop_stock` | Lecture shop_inventories exposée comme Product.stock en mémoire | Projection seulement ; ne doit plus masquer une autorité locale d'écriture. |
| Shop parent : mutations / listener | `adjust_stock`, `set_initial_shop_stock`, `set_shop_stock`, `_redirect_product_stock_changes_to_shop` | Product.stock si aucune boutique, sinon ShopInventory.stock ; listener `before_flush` redirige les anciens writers | Bloqueur majeur : modifier les appels seuls ne neutralise pas le listener. Plan d'adaptation et tests requis. |
| Shop parent : produits / réassort | `../app/routers/products.py` création, restock, update ; `../app/services/catalog_service.py` | Fonctions de contexte ci-dessus ; création stock 0 / ajustement / remplacement ; mouvement de réassort | Entrées et corrections Core versionnées, interdire boutique implicite. |
| Shop parent : ventes / annulations | `../app/routers/sales.py` | `adjust_stock(-quantity)` / `adjust_stock(+quantity)` ; journal StockMovement | Adaptateur Core, même clé vente/retry, aucune seconde mutation locale. |
| Shop parent : synchronisation hors ligne | `../app/pwa/offline-sales.js`, `../app/routers/sales.py:sync_offline_sale` | IndexedDB `offline_sale_id`, empreinte, déduplication backend, vérification boutique ; finit dans le writer vente Shop | La déduplication locale n'accorde pas de stock global. Préallocation Core avant livraison hors ligne, ou brouillon uniquement. |
| Shop parent : achats / annulations | `../app/routers/purchases.py` | `adjust_stock(+quantity)` / inversion ; journal StockMovement | À adapter avec toutes les entrées de stock, pas seulement ventes. |
| Shop parent : import photo de vente | `../app/services/sale_photo_import_service.py` | `adjust_stock(-row.quantity)` | Writer indirect obligatoire dans le plan ; import de vente doit partager l'idempotence Core. |
| Core actuel | `app/domains/core/public/stock.py` | Création/réservation, prolongation, libération, expiration, consommation de StockReservation ; **pas** de décrément Product.stock | Remplacé uniquement dans le laboratoire par Core v2. |
| Online checkout | `app/domains/online/public/checkout.py` | Réservations + commande + business transaction + outbox dans une Session | Saga cible ; aucun branchement réalisé. |
| Online statut / revalidation / paiement | `app/domains/online/internal/order_service.py`, `payment_service.py`, `reservation_policy.py` | Synchronisation Core, validation/consommation/libération/réservation au même commit | Saga, événements et compensations ; ne pas réutiliser le commit historique avec deux DSN. |
| Startup historique | `app/main.py`, `app/online_main.py`, installateurs de schémas | DDL/backfills tenant/policies ; pas un writer normal de vente mais peut changer les règles d'accès | Migrateur séparé et startup en lecture seule avant intégration ; inchangés ici. |
| Core laboratoire | `scripts/j43c/core.py` | Seul writer inventory/reservations/movements/receipts ; outbox locale | Exécuté uniquement avec `j43c_core_runtime`. |
| Online / Shop laboratoire | `scripts/j43c/orchestrator.py` | Commandes, paiements, outbox/inbox propres ; aucun accès SQL à inventory | Instances séparées, scripts de recette seulement. |

Les modèles `Product`, `StockMovement`, `ShopInventory`, `StockReservation` définissent les tables ; ils ne sont pas eux-mêmes les points d'entrée d'écriture. `shop_inventories` possède une unicité `(shop_id, product_id)` dans le parent ; la cible ajoute explicitement le tenant dans la clé métier et les contraintes locales. Les snapshots/vues analytiques et calculateurs de réapprovisionnement sont des lecteurs/projections, pas une autorité de stock. Le catalogue agent et les éditions génériques (`setattr`) doivent néanmoins être inclus dans le gel des writers.

Recherche utilisée : affectations `.stock`, constructions Product/StockMovement/StockReservation, SQL UPDATE/INSERT produits/inventaires, `adjust_stock`, `set_shop_stock`, `set_initial_shop_stock`, listeners et points d'entrée offline/import. Aucune preuve sur d'éventuels writers manuels ou distants n'est revendiquée.

## Stratégie hors ligne démontrée

1. Connecté : allouer Core pour le tenant, la boutique, le terminal et un order_id précis ; persister l'ACK dans Shop. Quantités non transférables à une autre vente/terminal.
2. Déconnecté : `record_offline_sale` refuse une allocation absente/non acquise ou une vente déjà associée à un autre identifiant. Persister vente locale et commande à émettre dans une transaction Shop.
3. Synchronisation : Confirm → Consume → RecordSale via les mêmes reçus/outbox/inbox. Répéter la synchro ou redémarrer le processus ne consomme pas deux fois.
4. Pendant la déconnexion, les autres canaux voient l'allocation comme réservée. Aucun timeout ou tick d'expiration ne la récupère automatiquement.
5. Sans préallocation, conserver un brouillon sans promesse de livraison. Un éventuel stock insuffisant à la reconnexion exige une décision métier, jamais une quantité négative cachée.

Ce mécanisme est un escrow **par vente**, pas un système complet de quotas réutilisables multi-terminaux. La caisse réelle, IndexedDB, l'authentification terminal, l'encaissement cash, le retour physique et la récupération de terminaux perdus ne sont pas intégrés par ce sprint. Le faux paiement hors ligne est une écriture synthétique locale, pas une preuve bancaire.

## Partie Shop arrêtée en attente d'autorisation

Travail préparé : inventaire ci-dessus, contrats v2, simulateur et plan de bascule ADR. Aucun writer ni listener Shop modifié. Une intervention ultérieure devra :

- adapter ventes, achats, annulations, réassorts, ajustements, agents et imports ;
- définir les commandes Core supplémentaires d'entrée/correction de stock ;
- remplacer le writer `before_flush` par une projection sans autorité ;
- intégrer et tester la caisse offline réelle et la réconciliation des allocations ;
- prouver le retrait des privilèges SQL directs et l'impossibilité de redémarrer l'ancien writer après bascule.

La seule autorisation du présent laboratoire ne vaut pas autorisation de ces modifications. Aucun patch Shop prêt à appliquer n'est caché dans cette livraison.

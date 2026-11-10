# ADR J4.3C-002 — Autorité du stock et transactions distribuées

Date : 2026-11-10. **Décision implémentée exclusivement dans le laboratoire** `scripts/j43c`. Base de revue : `d1e5dfa`. L'autorisation du sprint permet ce prototype ; elle n'autorise ni l'adaptation des writers Shop, ni une bascule.

## Décision

Core est l'unique autorité d'écriture du stock cible. La clé est `(tenant_id, shop_id, product_id)` ; `tenant_id` correspond à l'identité métier `merchant_id`, après validation explicite du mapping. Aucun identifiant NULL, nom de produit, numéro de téléphone ou boutique implicite ne sert de clé. Un tenant possède plusieurs boutiques ; aucune somme de stocks de boutiques n'autorise la vente d'une boutique donnée.

Les identifiants produits existants peuvent être conservés s'ils sont stables et rapprochés. Les nouvelles commandes ont un `order_id` UUID stable dans le namespace `(tenant, shop, source)`. Les références Online–Core sont logiques ; les FK ne traversent jamais les bases. Les FK locales incluent tenant et boutique.

Pour chaque clé produit :

- `physical` : stock physique **comptabilisé** par Core, entier >= 0 ;
- `reserved` : allocations actives/confirmées, y compris quotas hors ligne non réconciliés ;
- `available = physical - reserved`, toujours >= 0 ;
- `consumed` : consommations nettes des compensations dans le laboratoire ; le journal conserve séparément chaque consommation et chaque retour ;
- `version` : incrément à chaque modification du solde.

Réserver incrémente `reserved`. Confirmer ne modifie pas le solde ni l'échéance. Consommer décrémente **une seule fois** `physical` et `reserved`, incrémente `consumed` et écrit un mouvement `CONSUME`. `RecordSale` peut consommer un ensemble confirmé atomiquement, ou enregistrer une consommation existante sans second décrément. `CancelSale` écrit un mouvement inverse `RETURN`, sans effacer l'original. Le prototype couvre une annulation avant exécution matérielle ou un retour explicitement attesté ; il n'implémente pas un workflow de retours partiels après livraison.

Le consommé n'est **pas** retranché une deuxième fois de `physical`. C'est une différence volontaire avec le modèle historique Online, qui conserve `Product.stock` inchangé et retranche les réservations `consumed` lors de la lecture de disponibilité.

## Atomicité et concurrence

Chaque commande prend un verrou transactionnel sur son reçu, puis sur son agrégat commande, puis des verrous produits dans l'ordre des IDs. L'horloge PostgreSQL est lue après les verrous produits. L'ensemble multi-articles est tout ou rien. Les CHECK SQL empêchent les soldes négatifs ; les verrous protègent la décision métier concurrente. Les collisions du hash des verrous advisory ne font que sérialiser davantage.

Une transaction Core écrit effet, reçu immuable et résultat dans l'outbox. Une transaction Online écrit commande et outbox. La réception écrit inbox et transition de saga ensemble. Le transport ne promet que « au moins une fois ». Il n'y a ni 2PC, ni FDW/dblink, ni Session SQL commune, ni FK inter-base. Les connexions sont fermées avant tout appel de transport.

Un timeout ne prouve jamais l'échec. Online conserve `pending_key`, persiste `OUTCOME_UNKNOWN` et rejoue le même payload sous la même clé. Une annulation en attente ne libère ni ne restitue du stock avant de connaître l'état de la commande en vol.

## Hors ligne

Le laboratoire réserve un ensemble exact pour une vente/terminal avant déconnexion (`offline=true`, source Shop, `device_id` vérifié). Cette allocation n'expire pas automatiquement. La vente locale est durable dans la base Shop simulée ; la synchronisation consomme l'allocation et enregistre la vente. Le stock Core comptabilisé peut alors retarder la sortie physique, mais l'allocation reste indisponible aux autres canaux.

Sans allocation acquise, la vente hors ligne reste un brouillon et ne garantit pas la disponibilité. Interdire la livraison sans allocation est une condition métier de la garantie. Un terminal perdu ne permet pas de récupérer automatiquement son allocation : il faut prouver l'absence de ventes non synchronisées. Le protocole de récupération des terminaux et l'intégration IndexedDB réelle restent à réaliser avec autorisation Shop.

## Transition depuis l'autorité actuelle — plan arrêté avant exécution

1. Figer l'inventaire des writers et leur version, y compris listeners SQLAlchemy, imports photo, scripts et opérations manuelles. Faire approuver leur modification Shop séparément.
2. Établir le mapping tenant/boutique/produit. Mettre en quarantaine les références NULL, ambiguës ou sans boutique. Rapprocher `Product.stock`, `shop_inventories`, mouvements, réservations actives et consommées.
3. Définir un solde d'ouverture Core par clé, avec la preuve de chaque consommation historique déjà comptée ou encore à déduire. Ne jamais soustraire mécaniquement toutes les réservations `consumed` d'un stock déjà corrigé.
4. Implémenter et valider les adaptateurs Shop/Online, y compris achats, ajustements et imports — les sept commandes de vente ne couvrent pas ces writers entrants. Tester l'application complète et son démarrage avec rôles minimaux.
5. Lors d'une future fenêtre autorisée : fermer les writers concernés, drainer les opérations en vol, figer les files hors ligne, fixer un watermark et obtenir une sauvegarde vérifiée. La fermeture est par périmètre explicite, jamais un changement des pilotes.
6. Installer le solde Core validé ; retirer les privilèges de mutation de stock aux anciens runtimes et empêcher le redémarrage de leurs anciennes versions. Seul Core reçoit le droit d'écriture. Une feature flag seule ne suffit pas à neutraliser un ancien writer.
7. Ouvrir les adaptateurs après preuve des ACL, des files et du rapprochement. Aucune phase de double écriture. Les projections Shop/Online sont alimentées par événements et ne décident jamais de la disponibilité autoritaire.
8. Après de nouvelles écritures Core, rollback uniquement vers une application compatible avec Core ; ne pas repointer vers l'ancien stock partagé. Corriger en avant ou restaurer/rejouer de manière dédupliquée selon une procédure préalablement testée.

Les étapes 4–8 ne sont **pas réalisées**. Aucun changement de writer Shop n'est engagé ; cette partie attend une autorisation explicite.

## Sécurité et limites

Identités interservices synthétiques HMAC liées à un tenant, une boutique, une source et éventuellement un terminal. Signature sur méthode, chemin, timestamp et octets du corps ; comparaison constante, fenêtre 60 secondes, ressignature des retries. Les événements Core et confirmations de paiement ont des identités distinctes. Auth V2 est inchangé.

RLS ENABLE/FORCE, rôles runtime/worker non propriétaires sans SUPERUSER/BYPASSRLS ni membership owner/migrator. Contexte tenant **et** boutique transaction-local. Les GUC ne sont pas une authentification SQL : les credentials sont serveur et l'identité est vérifiée avant la transaction. Un runtime compromis peut choisir ses GUC ; cette limite ne se résout pas par une affirmation d'isolation absolue.

Sources primaires vérifiées : [RLS PostgreSQL 18](https://www.postgresql.org/docs/18/ddl-rowsecurity.html) et [verrous PostgreSQL 18](https://www.postgresql.org/docs/18/explicit-locking.html). FORCE RLS ne contraint pas un superuser/BYPASSRLS ; TRUNCATE exige des ACL distinctes. Le laboratoire teste ces refus avec les vrais logins.

Les clés synthétiques et `trust` Docker local ne constituent pas la gestion des identités, du TLS ou des secrets de production. La séparation est prouvée pour le prototype, pas pour les applications actuellement déployées.

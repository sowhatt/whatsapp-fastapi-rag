# J4.3D — Étude des quotas hors ligne

La file IndexedDB actuelle déduplique une vente et préserve sa boutique ; elle ne réserve aucune quantité globale. Avec deux terminaux hors ligne, un même stock affiché ne peut être une promesse de vente pour les deux.

## Mécanisme proposé

Un quota appartient à `(tenant, boutique, produit, terminal, allocation_id, epoch)`. Lorsqu'il est connecté, le terminal demande Q unités ; Core retire Q de la disponibilité dans une transaction verrouillée, écrit un reçu et émet l'allocation. Le terminal ne peut vendre qu'après réception et persistance de cet ACK. Le worker doit retrouver l'identité autorisée du terminal à partir de données durables ; les credentials ne proviennent pas du payload client.

La vente locale est une transaction unique : incrément monotone du compteur d'allocation, décrément du solde local, journal de vente avec `sale_id` stable et entrée de synchronisation. Un même `(allocation, sequence)` avec une empreinte différente est un conflit. Un doublon identique ne consomme rien. Limiter la somme débitée au quota ; interdire transfert de terminal, de boutique ou de produit.

Pendant la coupure, le Core maintient la réservation totale qui n'a pas encore été rapprochée. Elle couvre **les unités non dépensées ET les unités vendues mais non acquittées**. À la reconnexion, chaque consommation validée diminue simultanément physical et reserved ; les unités encore disponibles en ligne restent donc inchangées par ce rattrapage. Un retour local ne recrédite pas un quota avant validation de son reçu, de sa garde physique et de son caractère revendable.

Exemple : ouverture 10, quotas A=3 et B=2, réserve Online=1 ⇒ disponible partagé=4. A vend 2 hors ligne : disponible partagé reste 4. Après synchronisation : physical=8, réservations quotas=3, réserve Online=1 ⇒ disponible partagé=4. La même synchronisation répétée ne change plus les compteurs.

## Récupération et terminaux perdus

Un TTL de communication n'autorise **jamais** à restituer les unités : le terminal peut déjà les avoir vendues sans ACK. Clôture en deux phases : figer le terminal/son epoch, envoyer le watermark final et les ventes, obtenir leurs reçus, puis restituer seulement le non-dépensé prouvé. Un changement de clé réseau n'annule pas des ventes déjà réalisées.

Terminal perdu, volé, restauré depuis backup ou cloné : placer l'allocation en quarantaine, garder les quantités indisponibles et rapprocher physiquement. La duplication d'IndexedDB peut permettre deux livraisons physiques avec les mêmes jetons ; la déduplication serveur ne les annule pas. Une garantie complète exige une hypothèse explicite de terminal à journal unique non clonable, une protection matérielle/gestion de terminaux, ou des règles métier acceptant ce risque. On ne prétend pas fournir cette protection via une signature seule.

## Ce qui est effectivement testé

J4.3C implémente un séquestre **par vente/terminal**, non expirant (`expires_at IS NULL`). J4.3D utilise ce mécanisme avec deux terminaux et des identités distinctes sur une base Shop indépendante : allocation, ventes locales, refus Online lorsque toutes les unités sont réservées, redémarrage des workers, synchronisation répétée et refus de réutilisation avec un autre identifiant de vente. Les invariants avant/après reconnexion sont conservés dans `evidence/lab/invariants.jsonl`.

Ce laboratoire conserve le journal offline dans la base PostgreSQL Shop ; il ne simule pas IndexedDB ou une vraie coupure de navigateur. Une absence d'allocation ou d'ACK est refusée avant la vente. Les tests antérieurs réexécutés couvrent en outre les identités erronées, timeouts, crashs et doublons.

Un **quota réutilisable sur plusieurs ventes**, le comptage local atomique, les retours partiels, l'intégration IndexedDB, les clés terminal réelles, le protocole de clôture, la perte de terminal et les epochs restent à réaliser. Verdict : étude et séquestre par vente recevables pour le laboratoire ; **NO-GO pour activer des quotas dans les caisses pilotes**.

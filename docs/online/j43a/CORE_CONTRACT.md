# Contrat Core préparatoire v1

**Proposition, non raccordée au runtime.** Types : `app/domains/core/contracts/commands.py`.
L'interface `CorePort` est un protocole sans implémentation réseau. Aucun appel des services existants n'est remplacé.

## Enveloppe et idempotence

Commande : `version=1`, `command`, `merchant_id` entier positif établi côté serveur, `source` Online/Shop, `source_id` stable de l'opération d'origine, `idempotency_key` UUID, puis payload typé. Quantités entières strictement positives ; doublons produit refusés ; montants entiers en unités mineures de la devise (XOF : entier sans fraction). Champs inconnus refusés. Les tableaux de lignes sont canonisés par produit pour l'empreinte SHA-256 ; la clé elle-même en est exclue. Tout changement de tenant, source, opération, version ou payload change l'empreinte.

Unicité durable : `(merchant_id, source, idempotency_key)` pour toutes les commandes, et vérification du nom de commande + empreinte. Même clé et même contenu → résultat original, mêmes identifiants d'événements, aucun nouvel effet. Même clé et contenu différent → `IDEMPOTENCY_CONFLICT`. Ne pas dédupliquer seulement en mémoire ou par timestamp. Une nouvelle tentative d'une même opération après timeout conserve exactement la clé et le contenu. Une opération métier différente obtient une nouvelle clé.

Une transaction Core verrouille le reçu/agrégat, applique l'effet, écrit résultat et outbox puis commit. Un échec annule l'ensemble ; une erreur interceptée par l'appelant ne doit pas persister un reçu incomplet. La preuve locale `scripts/j43a/receipts.py` utilise un savepoint à l'intérieur d'une transaction explicitement possédée par l'appelant. Elle ne gère ni orchestration, ni argent, ni vente réelle.

Réponse de commande : clé, identifiant d'agrégat, version, état et IDs d'événements. Les statuts et réponses métier doivent être fermés par commande lors de l'implémentation approuvée ; `CommandResult.state` reste générique dans cette préparation. Les IDs de la cible proposés en UUID exigent le mapping des IDs entiers historiques (D4), pas une conversion silencieuse.

## Commandes, états et événements proposés

| Commande | Précondition / transition | Atomicité et événement après commit |
| --- | --- | --- |
| ReserveStock | Marchand/source vérifiés, ensemble non vide, produits du tenant, TTL 30–3600 s ; absent → active | Verrous produits dans ordre stable, échéance évaluée après acquisition, ensemble tout ou rien. Reçu + réservations + `core.stock.reserved.v1` dans Core. |
| ConfirmReservation | Ensemble complet active non expiré, `expected_version` exacte → confirmed | Bail confirmé selon politique serveur à valider ; jamais de résurrection d'un ensemble expiré. `core.reservation.confirmed.v1`. |
| ReleaseReservation | active/confirmed → released ; expiration Core → expired | Libérer exactement une fois, refus si consommé. `core.reservation.released.v1` ou `core.reservation.expired.v1`. Une raison client « expired » ne remplace pas la vérification de l'horloge Core. |
| ConsumeReservation | confirmed valide → consumed | Quantités exactes, consommation et mouvement dans Core, version incrémentée une fois. `core.reservation.consumed.v1`, `core.stock.changed.v1`. Modèle physique de comptabilisation soumis à D2. |
| RecordSale | Ensemble confirmé ou déjà consommé, source et montant/devise cohérents → vente enregistrée | Proposition D2 : transaction métier, consommation nécessaire et mouvement atomiques dans Core ; ne jamais doubler l'effet de ConsumeReservation. `core.sale.recorded.v1`. |
| CancelSale | Vente existante, version et motif vérifiés → cancelled/compensated selon D2 | Retour de stock uniquement si règle métier l'autorise ; mouvement inverse référencé, pas d'effacement du journal. `core.sale.cancelled.v1` et éventuellement `core.stock.changed.v1`. |
| GetStockAvailability | Produits du tenant, lecture de l'autorité | Quantité disponible, version et instant d'observation par produit. Réponse indicative : seul ReserveStock accorde le stock. Aucun événement ni réservation implicite. |

Le modèle historique utilise `active/consumed/released/expired` et la confirmation de commande prolonge les réservations actives. Le tableau ci-dessus ne change pas ce modèle ; le statut `confirmed` de réservation est une proposition cible à décider avec D2.

Tous les rejouements d'une commande déjà réussie retournent son résultat original même si l'état a évolué depuis ; une **nouvelle** clé avec une transition devenue interdite est refusée. `expected_version` protège contre les commandes hors ordre. Une expiration concurrente ne peut pas être ignorée par un client qui a attendu un verrou.

## Erreurs et transport à préparer

| Code | Comportement client proposé |
| --- | --- |
| NOT_FOUND | 404 générique pour absent ou hors tenant ; aucune révélation de l'existence étrangère |
| INSUFFICIENT_STOCK | 409, pas de retry aveugle ; présenter disponibilité autoritaire |
| EXPIRED | 409, nouvelle décision utilisateur et nouvel ensemble si réservable |
| VERSION_CONFLICT / INVALID_TRANSITION | 409, relecture de l'agrégat avant nouvelle décision |
| IDEMPOTENCY_CONFLICT | 409, erreur d'intégration ; ne jamais changer le payload sous la même clé |
| UNAVAILABLE | 503, retry borné pour incident transitoire |
| OUTCOME_UNKNOWN | État durable de l'orchestrateur après timeout/rupture ambiguë ; rejeu de la même commande pour retrouver son reçu ; pas de compensation aveugle |

Proposition transport à valider : connexion 2 s, requête 5 s, budget interactif total 15 s, au maximum 3 tentatives avec jitter exponentiel 100 ms→1 s à l'intérieur du budget. Timeout SQL et verrou Core inférieurs à la requête ; valeurs de départ 3 s / 1 s, à mesurer en charge. Réessayer uniquement indisponibilité, sérialisation ou deadlock reconnu, et toujours l'ensemble de la transaction locale. Les erreurs de validation, permissions ou métier ne se retryent pas automatiquement. Au-delà du budget : rendre l'état « traitement à vérifier » et reprendre côté serveur, sans accepter une seconde vente.

Les retries asynchrones proposés ont une échéance métier liée au bail et une file d'échec observable ; les seuils d'exploitation et la rétention doivent être validés. Ne pas supprimer les reçus pendant la fenêtre de retry, sauvegarde ou retour arrière. Les reçus de ventes doivent avoir une rétention compatible avec les obligations du journal métier, à décider avant implémentation.

## Événements et projections

Enveloppe cible : `event_id` UUID, version de schéma, type, tenant, agrégat, version d'agrégat, `occurred_at` UTC, `causation_id`/clé commande, corrélation, payload minimal. Une base n'écrit que sa propre outbox. Publication après commit ; accusé de publication durable ; les événements peuvent être livrés plusieurs fois et en désordre.

Inbox : `(merchant_id, consumer, event_id)` + empreinte, effet de projection et reçu dans un même commit. Même ID autre payload → erreur/quarantaine, pas mise à jour silencieuse. Une version obsolète ne remplace pas une projection plus récente ; un trou de séquence déclenche une relecture autoritaire. Pas de « dernier arrivé gagne » pour le stock. Les événements ne confèrent jamais une identité tenant ni un droit d'accès.

Le transport Core–Online, les watermarks, la reprise après crash interservices et la gestion du désordre ne sont pas implémentés par J4.3A (D1). Les tests outbox/inbox actuels vérifient les transactions locales et doublons ; les tests de saga multi-bases restent un prérequis J4.3B après validation.

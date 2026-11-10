# Contrats Core v2 — laboratoire J4.3C

Source exécutable : `scripts/j43c/contracts.py`. [JSON Schema](contracts-v2.schema.json). Le brouillon v1 de la PR #8 reste inchangé ; v2 ajoute notamment la boutique et une enveloppe commune à la lecture. Aucun client existant n'est basculé.

Endpoint FastAPI isolé : `POST /v2/stock/commands`. Création explicite par `create_app(core, keys)` ; aucun import du runtime existant, aucun DDL au lifespan. La recette utilise TestClient pour les parcours et un serveur Uvicorn réellement lié au loopback pour le timeout HTTP après commit ; aucun service n’est publié.

## Enveloppe et identité

Tous les appels portent `version=2`, `command`, `tenant_id>0`, `shop_id>0`, `source=online|shop`, `order_id` UUID, `idempotency_key` UUID et `device_id` optionnel. Le tenant, la boutique, la source et le terminal doivent correspondre à la clé interservice vérifiée. Les quantités sont des entiers stricts >0 ; doublons produits et champs inconnus sont refusés. Les lignes sont canonisées par produit.

Headers : `X-Key-Id`, `X-Timestamp` (secondes Unix), `X-Signature` HMAC-SHA256 de `POST\n<path>\n<timestamp>\n<body>`. Un timestamp signé de plus de 60 secondes est refusé. L'identité vient de la configuration serveur, pas du payload. Aucun secret réel n'est utilisé.

Unicité du reçu : `(tenant_id, shop_id, source, idempotency_key)`. Même clé/payload : résultat original, y compris ses erreurs métier et son `event_id`, sans effet supplémentaire. Autre payload sous la même clé : 409 `IDEMPOTENCY_CONFLICT`. Une nouvelle clé ne permet pas de recréer une réservation sur le même `order_id` : `ORDER_EXISTS`. Les reçus, mouvements et inbox n'ont aucun droit UPDATE/DELETE runtime, aucune purge automatique.

## Opérations

| Opération | Payload complémentaire et préconditions | Transition / effet |
| --- | --- | --- |
| ReserveStock | 1–100 lignes produit/quantité ; TTL 30–3600 s (600 par défaut) ; stock suffisant ; agrégat absent | ABSENT → ACTIVE, version 1 ; réserve toutes les lignes ou aucune. `offline=true` exige source Shop + terminal et crée une allocation sans échéance automatique. |
| ConfirmReservation | `expected_version` exacte ; ACTIVE, non expirée | ACTIVE → CONFIRMED ; version +1 ; aucune extension implicite du bail. |
| ReleaseReservation | version exacte ; ACTIVE/CONFIRMED ; raison cancelled/checkout_failed/expired | → RELEASED ; libère réservé. La raison expired n'est acceptée que si l'horloge Core prouve l'échéance ; alors → EXPIRED. Une réservation consommée ne peut pas être libérée. |
| ConsumeReservation | version exacte ; CONFIRMED, non expirée | → CONSUMED ; mouvement -quantité, réservé -quantité, consommé +quantité ; vente PENDING. |
| RecordSale | version exacte ; CONFIRMED non expirée ou CONSUMED avec vente PENDING ; devise ISO 3 lettres, montant entier mineur >=0 | Consomme si nécessaire puis vente RECORDED. Une consommation préalable ne provoque aucun nouveau mouvement. L'agrégat peut avancer de 2 versions si consommation et enregistrement sont combinés. |
| CancelSale | version exacte ; CONSUMED avec vente PENDING/RECORDED ; motif ; `return_to_stock=true` | → CANCELLED, vente CANCELLED, mouvement inverse une seule fois. Le caller de confiance atteste l'annulation avant exécution matérielle ou le retour ; les retours partiels ne sont pas supportés. |
| GetStockAvailability | même enveloppe, 1–100 IDs produits ; scope vérifié | Lecture `physical/reserved/consumed/available/version/observed_at` ; IDs hors scope absents. Pas de reçu ni d'outbox : rejouer une lecture donne une observation fraîche. La clé sert à la corrélation, pas à figer la disponibilité. |

Une expiration est évaluée après acquisition des verrous. Elle libère le réservé et produit un résultat durable `EXPIRED` avec l'état courant. Un tick `Core.expire(tenant,shop)` traite les échéances sans bypass. Si le tick tarde, le stock réservé reste conservativement indisponible ; le retard ne permet pas de survente.

## Réponses, erreurs et ambiguïtés

Une commande acceptée par Core reçoit HTTP 200 avec son résultat durable : `ok`, `error`, `state`, `aggregate_version`, `sale_state`, `event_id`. HTTP 200 ne signifie pas que `ok=true`. Les erreurs métier sont dans le reçu et l'événement, ce qui permet leur reprise durable. La saga utilise les événements Core comme preuve de transition.

| Résultat | Action |
| --- | --- |
| 401 signature/identité invalide ; 403 scope/source refusés | Aucun effet SQL ; pas de retry automatique avec la même identité invalide. |
| 422 INVALID_COMMAND | Corriger le contrat ; aucune mutation. |
| 409 IDEMPOTENCY_CONFLICT | Incident d'intégration ; conserver la clé et le payload d'origine pour investigation, ne pas remplacer silencieusement. |
| NOT_FOUND | Agrégat/produit absent ou non accessible ; ne pas révéler l'existence étrangère. |
| INSUFFICIENT_STOCK | Pas de retry automatique de la décision commerciale. Si un paiement est arrivé, compensation persistée. |
| VERSION_CONFLICT | Le reçu fournit l'état/version sous verrou. La saga adapte sa prochaine transition avec une nouvelle clé, sans changer l'opération en vol. |
| INVALID_TRANSITION, ORDER_EXISTS, NOT_EXPIRED | Erreur de protocole ou de décision ; `MANUAL_REVIEW` côté saga pour les erreurs non réconciliables. |
| EXPIRED | Aucun rétablissement automatique de l'allocation. Échec de commande et remboursement si capturé. |
| Timeout/connexion perdue | `OUTCOME_UNKNOWN`, opération toujours en attente. Rejouer exactement la même clé/payload ; une annulation attend d'abord cette résolution. |

Le prototype persiste `attempts` et `next_attempt_at` : backoff 1, 2, 4… plafonné à 60 secondes. Aucun changement de clé au retry. La fin du bail n'efface jamais une opération ambiguë. Les exceptions de processus/SQL provoquent rollback ou laissent l'outbox pending ; une invocation suivante reprend la même commande. Il n'existe pas de retry interne caché autour d'une transaction partiellement exécutée.

Le client `CoreTransport` accepte uniquement une origine HTTP loopback avec port explicite, sans proxy/netrc, sans redirection, connexion 2 s et lecture 5 s. Timeout, réponse illisible, 429 ou 5xx sont ambigus et restent rejouables ; les rejets de protocole/authentification mettent la saga en MANUAL_REVIEW, sans retry automatique.

Limites explicites : pas de transport HTTP d’exploitation/TLS, circuit breaker, jitter, deadline globale, interface opérateur de quarantaine ou alerte sur l’âge des files. L'ordonnanceur appelle `dispatch`, `publish` et `expire` avec un scope déjà autorisé. Il n'effectue pas de scan global privilégié. Ces fonctions sont exercées par la recette locale, pas activées dans les applications.

## Paiements et événements

Confirmation synthétique : corps typé `PaymentCaptured` v2, tenant/boutique, commande, `payment_id`, `event_id`, montant/devise exacts. Endpoint logique signé `/v2/payments/events`, identité `payment` distincte. Inbox + confirmation + prochaine commande Core dans le même commit. Un second ID de paiement pour une commande est refusé ; le même ID n'est pas réutilisable sur une autre commande du scope.

Core produit : version, event_id, scope, source destinataire, order_id, idempotency_key, command et résultat. L'événement est signé sur `/v2/core/events`. Même ID + même empreinte : aucun second effet ; même ID + autre contenu : conflit. Une version ancienne ne remplace pas l'état plus récent. Le retour de la commande en attente est traité même si un événement d'expiration plus récent a déjà été observé.

Un remboursement utilise une `refund_outbox` persistée. Le faux PSP déduplique par `(tenant, shop, payment_id)` dans la troisième instance sous un rôle distinct ; perdre son ACK ne rembourse pas deux fois. Le résultat `REFUNDED` de recette ne prouve aucun remboursement réel ni l'intégration d'un PSP opérationnel.

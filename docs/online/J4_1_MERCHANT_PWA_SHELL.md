# J4.1 — Merchant PWA Shell & Vertical Router

## Objectif et audit initial

J4.1 = shell, navigation, contexte, PWA et routeur vertical.
J4.2 = modules Commerce.
J4.3 = modules Restaurant.
J4.4 = modules Rental.

Base vérifiée après `git fetch origin` :
`origin/feat/whatzabi-online-s0-foundation`, SHA
`d4394d8f228c3117ee38cd69e8f7b4e0bb88c3f2`.
Dépôt initial propre, HEAD identique, `git diff --check` sans erreur.
Branche de livraison : `feat/whatzabi-online-j4-1-merchant-pwa-shell`.

L’application Online est assemblée dans `app/online_main.py`.
Le storefront est servi par `online_storefront_web.py`, ses assets sont dans
`domains/online/public/storefront_assets.py`. Le cockpit technique est dans
`online_admin_web.py`, avec `/online-admin-sw.js`, sans manifest marchand.
Les APIs administratives sont dans `online_admin.py`. Les services de commandes,
notifications, réservations et Web Push existent déjà. `OnlineStore` contient
`business_type`, `capabilities_json`, nom, pays et devise.

Aucune identité de session commerçant utilisable n’est présente dans cette branche.
`app.db.tenant.get_current_merchant` lit un contexte SQLAlchemy, initialisé pour le
traitement WhatsApp : ce n’est pas une preuve d’authentification HTTP.
Le token administratif du cockpit n’est pas utilisable comme session métier.

## Architecture et fichiers

- `app/merchant/identity.py` : contrat Auth V2, contrôle de rôle, origine et contexte RLS.
- `app/merchant/verticals.py` : registre unique des modules, capabilities et navigations.
- `app/routers/merchant_api.py` : BFF tenant-bound, projections minimales et françaises.
- `app/routers/merchant_pwa.py` : livraison des fichiers statiques et routes du shell.
- `app/merchant_pwa/index.html`, `styles.css`, `app.js`, `api.js`, `store.js`,
  `router.js`, `push.js` : application native sans build ni dépendance frontend.
- `components/app-shell.js`, `components/ui.js` : navigation, identité, badge,
  cartes, états vides, erreurs, icônes SVG et construction DOM sûre.
- `views/home.js`, `orders.js`, `notifications.js`, `module-placeholder.js` : vues.
- `manifest.webmanifest`, `service-worker.js`, `offline.html`, `assets/` : PWA et
  icônes locales SVG/PNG 192 et 512 px, sans téléchargement tiers.
- `tests/test_online_j41_{merchant_shell,vertical_router,merchant_api,pwa_assets,tenant_isolation}.py`,
  `tests/merchant_j41_support.py`, `tests/merchant_j41_sw_test.cjs` : validation.

Seul fichier préexistant modifié : `app/online_main.py`, pour brancher les deux
routeurs et les en-têtes/erreurs privés du BFF. Pas de migration ni changement de
schéma. Aucun changement dans `app.main`, Shop, les événements, les réservations,
l’outbox, les transports Push, la validation DNS, SSRF, allowlist ou VAPID.

Le BFF réutilise `list_orders`, `get_order`, `order_summary`, les modèles de
notifications et le chemin existant de validation/persistance des souscriptions
Push. Ce dernier est appelé en Python, jamais via les URLs administratives par
le navigateur. Le handoff WhatsApp réutilise `whatsapp_handoff_url` ; seul un clic
utilisateur ouvre `wa.me`, aucun message n’est envoyé automatiquement.

## Routes

| Méthode | Route | Fonction |
| --- | --- | --- |
| GET | `/merchant`, `/merchant/` | Accueil du shell |
| GET | `/merchant/orders` | Liste et détail via `?order_id=` |
| GET | `/merchant/notifications` | Notifications persistées |
| GET | `/merchant/catalog` | Présentation du module Produits non activé |
| GET | `/merchant/module/{module_key}` | Modules, Plus, Profil, Paramètres |
| GET | `/merchant/assets/{name}` | Assets publics, sans données métier |
| GET | `/merchant/manifest.webmanifest` | Manifest |
| GET | `/merchant/service-worker.js` | Worker marchand |
| GET | `/merchant-api/bootstrap` | Identité projetée, navigation, compteur |
| GET | `/merchant-api/dashboard` | Statistiques et activité réelles |
| GET | `/merchant-api/orders` | Pagination `limit`/`offset`, ou `order_id` |
| GET | `/merchant-api/notifications` | 100 dernières notifications et compteur global |
| PATCH | `/merchant-api/notifications/{id}/read` | Lecture persistée, corps `{}` |
| GET | `/merchant-api/push/config` | Activation et clé publique uniquement |
| POST | `/merchant-api/push-subscriptions` | Souscription du navigateur courant |

Chaque URL du shell fonctionne en accès direct et après rafraîchissement. Les
liens désactivés ouvrent une présentation « Module non activé », sans appel métier.
La liste des commandes affiche 25 éléments par page. Le détail permet le handoff
WhatsApp si le numéro existant est exploitable, sans l’exposer dans les listes.
Les commandes restent en consultation seule dans J4.1.

## Bootstrap

Exemple de forme, sans données de démonstration injectées dans l’application :

```json
{
  "merchant": {
    "display_name": "Nom configuré en base",
    "logo_url": null,
    "monogram": "NC",
    "business_type": "commerce",
    "business_label": "Commerce",
    "currency": "XOF",
    "country_code": "BJ"
  },
  "capabilities": ["catalog", "checkout", "notifications"],
  "navigation": [{
    "key": "home", "label": "Accueil", "href": "/merchant",
    "enabled": true, "mobile": true,
    "description": "Votre activité au quotidien.", "reason": null
  }],
  "configuration_required": false,
  "notifications": {"unread_count": 0},
  "pwa": {"push_enabled": false, "push_subscribed": null}
}
```

Le monogramme local est utilisé à la place d’un logo distant : aucune requête
vers une URL de logo arbitraire. `push_subscribed: null` signifie « inconnu du
serveur pour cet appareil ». Un abonnement actif d’un autre appareil ne constitue
pas une preuve d’abonnement ici ; `PushManager.getSubscription()` le résout lors
de l’activation explicite. Aucun identifiant de tenant n’est exposé. Les seuls
identifiants de ressources servent aux liens de commande et au marquage lu.

## Verticales et capabilities

Le registre Python est la seule source de navigation ; le JavaScript le rend,
sans liste parallèle de verticales ou fallback implicite vers Commerce.

| Verticale | Navigation mobile | Modules supplémentaires |
| --- | --- | --- |
| Commerce | Accueil, Commandes, Stock, Produits, Plus | Clients, Notifications |
| Restaurant | Cuisine, Commandes, Menu, Disponibilités, Plus | Livraisons, Clients, Notifications |
| Location | Calendrier, Réservations, Équipements, Retours, Plus | Cautions, Clients, Notifications |

Accueil, Profil et Paramètres restent accessibles depuis Plus et le menu desktop.
Une capability absente conserve le module visible avec état explicitement non
activé. Même présente, elle n’active pas un module non implémenté. Les contrôles
sont répétés côté BFF (403), indépendamment de la navigation.

- Commandes : `checkout`, seulement Commerce et Restaurant.
- Notifications et Push : `notifications`.
- Produits/Stock/Menu/Disponibilités/Équipements : `catalog`, présentation seulement.
- Livraisons : `delivery`, présentation seulement.
- Cautions : `payments`, présentation seulement.
- Cuisine/Calendrier/Réservations/Retours/Clients : contrats futurs, jamais de faux chiffres.
- Configuration JSON malformée : aucune capability accordée.
- Configuration absente (`null`) : défauts de la verticale déjà définis par Online.
- Type inconnu, y compris Service non livré : configuration générique sûre,
  aucune capability métier, message « Configuration à compléter ».

Le dashboard Commerce/Restaurant compte les vraies commandes par statut,
les paiements restant à traiter hors commandes annulées et les commandes dont le
stock doit être revalidé. Les cinq dernières commandes proviennent du service
existant. Les alertes de stock sont celles des réservations de commandes : les
seuils d’inventaire détaillés restent pour J4.2. Location affiche les notifications
et les emplacements futurs, aucune réservation ou caution synthétique.
Les statuts inconnus deviennent « À vérifier » ; `consumed` n’est pas exposé.

## Identité, Auth V2 et sécurité

`MerchantIdentityResolver.__call__(Request) -> MerchantIdentity` est le contrat.
Il renvoie toujours HTTP 401 dans cette livraison. Seuls les tests utilisent
`app.dependency_overrides[resolve_merchant_identity]`. Aucun paramètre de requête,
header ou variable de staging ne peut activer un autre comportement.

Contrat d’adaptation Auth V2 Passkeys à réaliser dans une revue dédiée :

1. Valider la session existante côté serveur (signature ou identifiant opaque,
   expiration, révocation et liaison au sujet authentifié).
2. Charger l’appartenance active du sujet à la boutique côté serveur, vérifier le
   rôle commerçant. Retourner `MerchantIdentity(merchant_id, subject, role)` ;
   aucune sélection de tenant issue du navigateur.
3. Session absente/invalide/révoquée : 401. Rôle incorrect : 403. Boutique absente : 404.
4. Utiliser les cookies Auth V2 Secure, HttpOnly, SameSite approprié, idéalement
   host-only. Ne pas créer de mot de passe ou de token administratif alternatif.
5. Relier connexion et déconnexion aux routes officielles Auth V2 lorsqu’elles
   existent. J4.1 n’invente ni URL de login ni faux bouton de déconnexion.
6. Déconnexion : révoquer la session serveur puis vider l’état mémoire et l’interface.
   Réévaluer l’abonnement Push de l’appareil dans cette intégration, en particulier
   sur appareil partagé. Ne jamais réattribuer automatiquement un endpoint à un
   autre tenant. Les collisions d’endpoints sont refusées (409).
7. Vérifier HTTPS/origine externe avec la configuration de proxy de confiance.
   Ne pas faire confiance à un header forwarded arbitraire pour contourner CSRF.

Avant toute lecture métier, la dépendance applique `apply_rls_context` sans bypass,
puis filtre explicitement `merchant_id` dans les requêtes SQL. Les notifications
sont restreintes au rôle merchant et au canal in-app. Les endpoints de mutation
vérifient origine exacte + header non simple `X-Merchant-Request: 1`, et Fetch
Metadata lorsqu’il est présent. Les lectures cross-origin sont également refusées,
sans changer la politique CORS des routes historiques.

Les sélecteurs de tenant en query/header/corps sont rejetés ; les champs de requête
sont fermés. Toutes les réponses BFF, y compris 401/403/422/500, sont `no-store,
private`. Les erreurs de validation ne renvoient pas les valeurs d’entrée.
Le BFF ne renvoie pas les endpoints ni clés de souscription. Les erreurs de base
sont génériques. Aucun stockage navigateur persistant, aucune donnée métier dans
le HTML, aucune construction `innerHTML` avec des données. CSP same-origin,
`frame-ancestors 'none'`, `nosniff` et absence de référent sur le shell.

Les mutations ne sont jamais mises en file hors ligne. Le frontend efface son état
mémoire et sa vue lors d’une perte de session, mise en arrière-plan ou perte du
réseau, puis revalide l’identité à la reprise et à chaque navigation. Le logout
serveur et sa coordination multi-onglets restent dépendants d’Auth V2.

## UX, PWA et hors ligne

Design mobile-first : palette vert profond/ivoire, monogramme et SVG locaux,
cartes compactes, sidebar desktop, navigation basse mobile, safe-area iOS,
largeur minimale 320 px, focus visible, lien d’évitement, zones tactiles de 44 px,
états de chargement, erreurs actionnables et états vides sans données fictives.
Le bouton Installer utilise l’événement natif lorsque disponible ; Paramètres
explique aussi l’ajout à l’écran d’accueil sur iPhone. Pas de prompt Push automatique.

Le service worker dédié a le scope `/merchant` (en-tête `Service-Worker-Allowed`).
Ce préfixe couvre aussi techniquement `/merchant-api` : les API sont explicitement
exclues du gestionnaire de fetch avant tout `respondWith`. Les anciens abonnements
et `/online-admin-sw.js` sont conservés. Le nouveau worker adapte les liens Push
`/online-admin-ui#order-N` en `/merchant/orders?order_id=N`, refuse les destinations
arbitraires et n’affiche pas le contenu sensible sur l’écran verrouillé.

Le précache est une allowlist exacte de fichiers statiques. Pas de `cache.put`
sur une réponse réseau, pas de cache des réponses de navigation, pas de cache
avec paramètres, pas d’API/admin/storefront/Push/client/commande. Le repli de
navigation utilise uniquement le shell statique précaché ; la page offline reste
un second repli. Sans réseau, les données et mutations sont indisponibles et
l’interface affiche « Vous êtes hors ligne ». Seuls les anciens caches préfixés
`whatzabi-merchant-shell-` sont nettoyés lors de l’activation.

Installation réelle : nécessite HTTPS (ou localhost), support du navigateur et
première visite en ligne. Les versions d’assets et worker doivent être incrémentées
ensemble aux prochaines évolutions. Les abonnements Push existants ne sont ni
migrés ni supprimés. Aucun envoi Push réel effectué dans les tests de cette livraison.

## Validation et limites

Python obligatoire : `/Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python`.
Toutes les suites Python ont été exécutées avec `DATABASE_URL=sqlite://`.
La baseline avant modification : **168 passed, 435 warnings**.
La suite prescrite après implémentation : **168 passed, 435 warnings**.
Résultats finaux : J4.1 **40 passed, 141 warnings** ; suite complète du dépôt
**787 passed, 1934 warnings**. Compilation Python, syntaxe JavaScript, test exécuté
du service worker et `git diff --check` : PASS. Les warnings restent visibles
dans les décomptes ; ils ne sont pas assimilés à des échecs.

Commandes :

```sh
DATABASE_URL=sqlite:// /Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -m pytest tests/test_online_j41_merchant_shell.py tests/test_online_j41_vertical_router.py tests/test_online_j41_merchant_api.py tests/test_online_j41_pwa_assets.py tests/test_online_j41_tenant_isolation.py -q --disable-warnings
DATABASE_URL=sqlite:// /Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -m pytest tests -q --disable-warnings
node tests/merchant_j41_sw_test.cjs
/Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -m compileall app
git diff --check
```

Le test JS utilise uniquement le runtime Node déjà installé, sans package, build
ou chaîne Node ajoutée au projet. Il exécute le worker dans un contexte simulé et
vérifie cache, exclusion des données sensibles, offline et liens Push. Les fichiers
JS sont également vérifiés avec `node --check`.

Les tests Python couvrent 401/403, les verticales, capabilities, compteurs réels,
marquage persistant, fuite inter-tenant, isolation des souscriptions, refus des
sélecteurs client, CSRF, projection WhatsApp, assets et compatibilité des routes.
Les tests SQLite vérifient les filtres et l’appel du contexte RLS ; ils ne constituent
pas une exécution des politiques PostgreSQL sous rôle applicatif réel.

Recette navigateur non validée : un premier accès Chrome a expiré et le second
n’a pas été approuvé par l’outil Computer Use. Aucun contournement. Il reste à
vérifier visuellement 320/390/768/1440 px, clavier, installation Android/iOS,
service worker dans un vrai navigateur, reprise réseau et Push sur appareil.
Le serveur de vérification local a été arrêté.

La livraison de code ne constitue pas un GO d’ouverture aux commerçants : Auth V2,
recette navigateur/appareils et validation RLS PostgreSQL restent à terminer.
Statut J4.1 : implémentation et validation automatisée terminées ; **NO-GO de recette
finale** tant que la vérification visuelle et PWA sur navigateur n’a pas été effectuée.
L’absence d’Auth V2 est le comportement fail-closed explicitement prévu par J4.1,
et reste un blocage séparé pour toute mise en service métier.
Aucune donnée réelle accessible en runtime sans Auth V2, aucun déploiement,
aucun changement Railway, aucune fusion Auth/Shop/Online.

## Plan précis J4.2 et extensions

1. Brancher Auth V2 Passkeys après revue séparée : session, appartenance, rôle,
   expiration/révocation, logout serveur et multi-onglets, cookies et CSRF.
2. Exécuter la recette responsive/PWA et les tests PostgreSQL tenant A/B sous rôle
   applicatif ; vérifier notamment isolation après commit et réutilisation du pool.
3. Construire les écrans Commerce Produits/Stock à partir des services Online/Core,
   sans modifier les workflows Shop ; activer les entrées du registre seulement
   quand leurs lectures et mutations sont livrées et autorisées.
4. Ajouter les actions commandes : confirmer, préparer, prête, terminer, annuler,
   revalider le stock et traiter les paiements déjà supportés ; réutiliser les
   transitions et protections d’idempotence existantes, toujours tenant-bound.
5. Ajouter recherche/filtres, pagination stable et détail métier complet, erreurs
   de concurrence, seuils de stock et compteurs contextualisés. Vérifier les index
   et coûts du dashboard sur un volume représentatif ; le service de résumé
   existant peut parcourir toutes les commandes en attente.
6. Compléter les préférences Push : état appareil fiable, désabonnement et gestion
   sécurisée des appareils partagés. Conserver strictement le transport J3.4C.
7. Étendre les tests de permissions, transitions, états offline, notification
   persistée, accessibilité et non-régression Shop/Online avant activation pilote.

J4.3 : modules Restaurant (Menu, Disponibilités, puis Cuisine) dans le même registre,
avec contrats dédiés, sans métriques fictives. J4.4 : modules Rental (Équipements,
Calendrier, Réservations puis Retours/Cautions) après définition de leurs invariants.
J4.1 ne crée ni réservations Rental, ni ingrédients, ni cuisine complète, ni Mobile
Money, ni Delivery complet, ni moteur d’authentification.

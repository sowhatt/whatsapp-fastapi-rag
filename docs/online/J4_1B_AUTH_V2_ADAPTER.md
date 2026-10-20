# J4.1B — Audit Auth V2 et prérequis de l’adaptateur Merchant

## Statut de livraison

**NO-GO Auth. L’adaptateur de session réelle n’est pas livré.**

L’audit a révélé que la source Auth V2 ne fournit ni session métier en cookie
HttpOnly, ni transfert de session vers Online, ni logout serveur de ses JWT.
Les contraintes imposent de laisser cette source en lecture seule, de conserver
un moteur unique et de ne pas transmettre de JWT au JavaScript Online. Il n’est
pas possible de raccorder un parcours réel respectant ces contraintes par la seule
réutilisation du contrat présent.

Cette branche livre les travaux indépendants : audit, contrat cible documenté,
extraction du service Push et tests des frontières de sécurité existantes.
`MerchantIdentityResolver` reste inchangé et renvoie 401 en runtime. Aucun
`dependency_override` n’est activé hors des tests. Aucune session simulée, route de
callback factice, nouvelle table de sessions ou copie du moteur WebAuthn.

Une question de périmètre a été soumise : attendre une extension de l’autorité
unique ou préparer un composant partagé destiné à cette autorité, à intégrer dans
une revue distincte. Aucun travail dépendant de cet élargissement n’a été effectué.

## Références et baseline

- Online : `eac6c7a351d983834e9c60b6a4ec93b4242f3288`, HEAD et
  `origin/feat/whatzabi-online-j4-1-merchant-pwa-shell` vérifiés après fetch.
- Branche enfant : `feat/whatzabi-online-j4-1-auth-v2-adapter`, inexistante localement
  et dans les références distantes après fetch avant sa création.
- Source auditée en lecture seule : `/Users/rkjo/Projects/whatzabi-shop-integration`.
- Branche source constatée : `feat/whatzabi-shop-auth-integration`.
- Merge annoncé : `021dfee`. HEAD réellement présent et propre :
  `c0eb872a54f86ad0ba93846f0ba2cdc4b38e1f71`.
- Trois commits après le merge : `9bc5da3` (scope boutique), `3caf71a`
  (activation/invitations), `c0eb872` (revue d’accès et sessions mémoire).
- Le diff ciblé entre le merge et HEAD a été inspecté : aucune nouvelle interface
  de session/callback inter-application. La limite constatée n’est pas résolue par
  les évolutions postérieures au merge annoncé.
- Baseline prescrite avant modification : **188 passed, 324 warnings**.

Pendant la vérification finale, le worktree source a présenté des modifications
non commitées concurrentes, notamment dans `app/auth.py`, les routes Auth et les
services de sécurité. HEAD est resté `c0eb872`. Le diff Auth observé ajoute
`auth_time` et une page de demande d’appareil, sans fournir le transfert/session
métier manquant. Ces travaux en cours ne sont ni intégrés ni considérés comme un
contrat validé ; l’audit de référence reste attaché au commit cité.

Aucun fichier du worktree source modifié par cette tâche ; aucun import/exécution de son application,
aucune fusion, aucun cherry-pick, aucun navigateur, aucune lecture de secret.

## Matrice de réutilisation

| Classe | Élément | Décision |
| --- | --- | --- |
| Réutilisable tel quel côté autorité | Vérification WebAuthn, UV, origine/RP, challenges consommés et binding navigateur | Conserver le moteur unique ; ne pas le copier dans Online |
| Réutilisable tel quel côté autorité | `merchant_users.merchant_id`, activité utilisateur, révocation Passkey, abonnement merchant | Sources de vérité à consulter après preuve validée |
| Après extraction/revue | Validation d’identité, liaison de compte, contrôles de rôle | Le code existant est couplé au Bearer et au scope Shop ; aucune extraction aveugle |
| Après extraction, réalisé | Validation/persistance de souscriptions Push | Service commun appelé par les deux routeurs Online |
| Spécifique Shop | `/auth/app`, `/select-shop`, rôles locaux, `shops`, `user_shop_memberships`, `user_phones` | Ne pas importer l’interface ni conférer un accès tenant global à un rôle local |
| Spécifique enrôlement | Sessions opaques S1.5, appareils, PIN | Ne confèrent aucun accès métier ; non réutilisables comme session Online |
| Absent | Cookie de session métier, login fédéré, callback, introspection, logout/révocation de JWT individuel | Prérequiert une évolution de l’autorité unique |
| Risque/dette | JWT sans issuer/audience/jti ; logout navigateur ; credentials liés à une origine exacte | Ne pas accepter silencieusement ces limites dans l’adaptateur Online |

## Fichiers source et contrats examinés

Tous les chemins de cette section sont relatifs au worktree source, pas des fichiers
copiés dans Online :

- `app/auth.py` : création HS256, validation Bearer, utilisateur actif, rôle en base,
  scope boutique et révocation Passkey.
- `app/routers/auth.py` : login, `/me`, liste/sélection boutiques, activation,
  interface Shop et assets.
- `app/routers/passkeys.py`, `app/services/passkey_service.py` : options/vérifications
  registration/authentication, révocation, cookies de challenge et retour Bearer.
- `app/routers/quick_auth.py`, `app/services/quick_auth_service.py` : enrôlement,
  contrôle de sessions opaques, expiration et révocation ; pas de login PIN.
- `app/models/merchant_auth_session.py`, `merchant_auth_device.py`,
  `merchant_user.py`, `merchant_passkey.py`, `user_shop_membership.py`,
  `activation_invitation.py` : identité, contraintes et états de révocation.
- `app/services/subscription_access_service.py` : statuts merchant autorisés
  `pilot`, `trialing`, `active`, `grace`, et expiration d’abonnement.
- `app/services/activation_invitation_service.py` : une invitation consommée ne
  constitue pas une session de connexion ou une autorisation de réinitialisation.
- `app/pwa/passkeys.js`, parties auth/logout de `app/pwa/app.js` : cérémonie native,
  JWT en mémoire, suppression d’anciennes entrées persistantes, logout local.
- `migrations/001_s1_5_pin_enrollment.sql`, `002_s1_6_webauthn.sql` et références
  migrations/tests de sécurité V2.1 ; `requirements.txt`.
- `docs/auth-v2/AUTH-V21-ARCHITECTURE-ET-RECETTE.md`,
  `docs/auth-v2/RAPPORT-V21-2026-10-20.md` : limites explicites des sessions mémoire
  et de la révocation globale, confirmées par le code.

### Routes Auth réellement présentes

- `POST /auth/login` : authentification par mot de passe, réponse JWT.
- `GET /auth/me`, `GET /auth/shops`, `POST /auth/select-shop` : Bearer et scope Shop.
- `GET /auth/app` : interface Shop, pas un fournisseur SSO pour Online.
- `POST /auth/passkeys/authenticate/options` et `/authenticate/verify` : challenge,
  assertion WebAuthn vérifiée et émission du JWT Bearer.
- `/auth/passkeys/register/options`, `/register/verify`, `/revoke`, `/recover`,
  `/pin/reset` : gestion des credentials et récupération.
- `/auth/quick/devices/enroll`, `/pin/setup`, `/devices/revoke`, `/recover` :
  enrôlement uniquement.
- `/auth/activation/status`, `/activate` : invitations.

Aucun `/authorize`, `/callback`, `/introspect` ou logout serveur métier compatible
n’a été trouvé. Aucun endpoint Auth n’est ajouté dans cette livraison partielle.

### Preuves et cookies

La preuve métier est un JWT HS256 avec `sub` représentant le merchant, `merchant_id`,
`iat`, `exp`, `type`, et selon le parcours `user_id`, `role`, `shop_id`, `passkey_id`,
`amr=webauthn`. La durée émise est plafonnée à 900 secondes au HEAD audité ; la
sélection de boutique préserve l’expiration initiale. La validation relit utilisateur,
rôle et credential. Pas d’issuer/audience/jti émis, pas de registre des JWT métier,
pas de refresh token ni protocole de rotation de session métier constaté.

Les cookies existants sont host-only, Secure, HttpOnly, SameSite=Strict, Path=/ :

| Usage | Durée | Autorisation |
| --- | --- | --- |
| Enrôlement | 300 secondes | Gestion de l’enrôlement seulement |
| Binding des challenges Passkey | 180 secondes | Liaison de la cérémonie, aucune session métier |
| Suivi de demande de récupération | 24 heures | Suivi uniquement, aucune connexion |

Les sessions opaques sont recherchées par hash SHA-256 et vérifiées avec leur
purpose, appareil, utilisateur, tenant, activité, expiration et révocation. Les
bindings WebAuthn sont comparés en temps constant. Aucun de ces cookies ne doit
être promu en session métier Online.

Les invitations stockent un hash et des dates d’expiration/utilisation/révocation.
Elles ne constituent pas une preuve d’identité réutilisable par MerchantIdentity.

## Décision d’architecture

A (package/service partagé déjà propre) : absent.
B (extraire uniquement une validation de session) : insuffisant, faute de cookie
métier et de mécanisme d’établissement/transfert de session conforme.
C (adaptateur Online du contrat Auth V2) : cible recommandée **après extension
reviewée de l’autorité**, sans duplication du moteur WebAuthn.

Ne pas accepter le JWT historique sans issuer/audience, ajouter un endpoint qui
reçoit ce JWT depuis le JavaScript, utiliser les sessions d’enrôlement, ou créer
une base Online concurrente de credentials/sessions. Ne pas simuler une réussite
à l’aide d’un cookie de test ou d’un override runtime.

### Contrat cible à convenir avec l’autorité unique — non implémenté

1. Définir le déploiement d’origine : même origine via routage dédié, ou fournisseur
   distant avec protocole standard de transfert. Le RP actuel exige un host/origine
   exact : une Passkey Shop ne s’utilise pas automatiquement sur un autre domaine.
2. L’autorité unique réalise la cérémonie et établit une session métier révocable,
   en cookie Secure/HttpOnly/host-only, SameSite adapté, durée limitée. Une seule
   source de vérité stocke son hash/expiration/révocation et sa liaison au sujet.
3. Si un transfert inter-origine est nécessaire, définir l’échange serveur-à-serveur
   et le binding de la tentative au navigateur, la protection contre rejeu et le
   retour interne. Aucun token de session/JWT dans URL, fragment ou réponse JS.
   Les URLs et paramètres exacts ne peuvent être inventés avant ce contrat.
4. Online valide la preuve via cette autorité ou le stockage partagé autorisé,
   vérifie expiration/révocation, utilisateur actif et association au merchant,
   abonnement merchant et rôle tenant explicite. Ne pas assimiler automatiquement
   SELLER/MANAGER local à un propriétaire de l’OnlineStore tenant-wide.
5. Après validation seulement :
   `MerchantIdentity(merchant_id=<serveur>, subject=<sujet vérifié>, role="merchant")`.
   Aucun claim client non vérifié ni sélecteur tenant frontend.
6. Cookie absent/invalide/expiré/révoqué : 401 ; rôle insuffisant : 403 ; association
   inactive/absente : refus ; indisponibilité de l’autorité : fail-closed.
7. Si le contrat choisi reste JWT, exiger algorithme fixe autorisé, issuer, audience,
   exp, nbf éventuel, durée maximale et mécanisme de révocation, sans réémettre en JS.
8. Logout : mutation protégée, révocation côté autorité et suppression du cookie
   avec exactement les mêmes attributs/path/domain ; purge de l’état mémoire
   Online et coordination multi-onglets sans diffuser de credential.
9. Connexion : état 401 professionnel, bouton vers le parcours réellement convenu.
   Retour vers une route `/merchant` explicitement autorisée seulement ; refuser
   URL absolue, `//`, backslash, contrôles, double encodage et destinations externes.

Le shell, le resolver et le contrat `MerchantIdentity` J4.1 restent inchangés tant
que ce raccord n’est pas possible. Aucun bouton factice ou redirect vers le Shop
sans retour authentifié n’est livré comme « connexion Online ».

## CSRF, RLS et cache existants

Les mutations Merchant API gardent l’origine exacte, Fetch Metadata et le header
non simple `X-Merchant-Request: 1`. Les clés de requête sont fermées et les sélecteurs
de tenant rejetés. Les routes sensibles appliquent le contexte RLS puis des filtres
explicites tenant. Les tests J4.1 couvrent commandes, notifications et souscriptions
A/B après override d’identité ; ils ne constituent pas une preuve de session Auth réelle.

Le service worker garde exclusivement son allowlist statique. Les futures routes
session/login/logout/callback ne correspondent ni au précache ni aux routes de
repli de navigation existantes. Les réponses Merchant API sont `no-store, private`.
Aucun stockage de session en localStorage/sessionStorage/IndexedDB. Aucun cache
métier ni modification de l’ancien worker administratif.

## Extraction du service Push réalisée

Nouveau `app/shared/notifications/subscription_service.py` :

- Schémas de payload partagés, champs inconnus refusés, valeurs exclues du repr.
- Validation d’entrée avec erreurs métier structurées et messages constants.
- Appel du validateur SSRF existant sans changement de règles.
- Tenant explicite backend, contexte RLS, recherche par tenant + endpoint.
- Création ou réactivation dans le tenant courant uniquement.
- Collision globale d’endpoint : rollback et erreur 409, jamais de réattribution.
- Réapplication RLS après commit avant refresh.

`online_admin.py` et `merchant_api.py` appellent ce service ; plus d’import d’un
routeur dans l’autre. Les URLs, statuts de succès et formats de réponse sont
conservés. Le cockpit garde sa réponse avec id ; le BFF ne renvoie que l’état actif.
Le rejet des champs supplémentaires et la réponse générique 409 dans le cockpit
sont les seuls durcissements additionnels. Transport, DNS pinning, allowlist, VAPID,
schémas et tables protégées ne sont pas modifiés.

## Dépendances DB et Python

L’autorité utilise notamment `merchant_users`, `user_phones`, `shops`,
`user_shop_memberships`, `activation_invitations`, `merchant_auth_devices`,
`merchant_auth_sessions`, `merchant_pin_credentials`, `merchant_auth_attempts`,
`merchant_passkey_users`, `merchant_passkeys`, `merchant_passkey_challenges`,
`merchant_passkey_rate_limits`, `merchant_auth_schema_versions`.
Les sessions présentes ont purpose `enrollment` ; aucun inventaire de sessions
métier ne peut être déduit de ces lignes.

Dépendances Auth : `PyJWT>=2.9,<3`, `webauthn==3.0.1`, PostgreSQL pour les verrous,
UPSERT et budgets partagés. Aucune de ces dépendances ni aucun modèle Auth n’est
importé ou copié dans Online. L’extraction Push n’ajoute aucune dépendance.

Présence de tables dans la base PostgreSQL partagée **non vérifiée** : aucune
connexion staging ni lecture de credentials autorisée/réalisée. Aucune migration
préparée pour un modèle de session métier encore indéfini ; une migration additive
versionnée devra être fournie par l’autorité une fois le contrat validé, puis
examinée séparément. Aucune migration ni écriture staging exécutée.
Pas de test PostgreSQL de session réelle possible pour ce contrat absent. Les tests
d’isolation livrés ici utilisent SQLite et ne prouvent pas les politiques RLS sous
rôle PostgreSQL non propriétaire.

## Tests et couverture honnête

Les commandes Python utilisent exclusivement
`/Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python`, avec `DATABASE_URL=sqlite://`.

Nouveaux tests :

- `test_online_j41_push_subscription_service.py` : 14 cas de validation,
  réactivation, collision inter-tenant, RLS et SSRF.
- `test_online_j41_auth_adapter.py` : 8 cas de refus des preuves non supportées,
  sans override et sans promotion des cookies d’enrôlement/challenge.
- `test_online_j41_csrf.py` : 12 cas sur les deux mutations, après override de
  l’identité de test, sans prétendre à une session réelle.
- `test_online_j41_session_security.py` : 2 contrôles statiques du stockage
  navigateur, des imports et du cache statique.

Total nouveaux tests : **36 passed, 21 warnings** lors de leur exécution ciblée.
Suites finales réellement exécutées :

| Suite | Résultat |
| --- | --- |
| 40 tests J4.1 initiaux | 40 passed, 141 warnings |
| Tous les fichiers `test_online_j3*.py` | 156 passed, 207 warnings |
| Tous les fichiers `test_online*.py` | 323 passed, 1773 warnings |
| Dépôt complet | 823 passed, 1952 warnings |
| Compilation `compileall app` | PASS |
| `git diff --check` | PASS |

Les warnings ne sont pas comptés comme des échecs. Aucun PASS n’est revendiqué
pour une connexion réelle Auth V2 ou un logout métier qui n’existent pas ici.

Ne sont **pas** validés : cookie métier accepté, authentification réussie depuis
Auth V2, expiration/révocation d’une session réelle, logout serveur/cookie de logout,
open redirect du futur callback, RLS PostgreSQL réel. Ces tests ne sont ni simulés
ni comptés comme passants. Les fichiers de test logout/auth-tenant réels demandés
ne sont pas créés artificiellement avant l’existence de ce contrat.

## Recette staging future — aucune action exécutée

1. Faire approuver et livrer le contrat de session dans l’autorité unique ; fixer
   les origines/RP, audience, mapping rôles et responsabilité des migrations.
2. Construire l’adaptateur Online et ses tests complets en local, y compris les
   sessions réelles et PostgreSQL 16 isolé sous rôle non propriétaire pour RLS.
3. Vérifier ensuite, via procédure opérateur sans affichage de secrets, les versions
   de schéma et les configurations d’origine dans l’environnement dédié Online.
4. Après autorisation distincte, appliquer uniquement la migration additive
   approuvée et déployer sur l’environnement Online isolé, jamais Shop staging.
5. Recetter deux comptes/tenants : connexion, bootstrap, rôle refusé, compte inactif,
   expiration, révocation, logout, retour interne, CSRF, notification et Push.
6. Réexécuter J4.1/J3/SSRF et vérifier logs, caches et cookies sans capturer leurs
   valeurs. Aucun de ces scénarios ne peut être présenté comme déjà recetté ici.

## Rollback et risques restants

Le sous-lot Push se retire par revert de son commit, sans migration ni suppression
de souscription ; les formats persistés restent ceux de J3.4. La documentation et
les tests se retirent séparément si nécessaire. Le resolver étant inchangé, cette
branche ne peut ouvrir involontairement l’accès à des comptes réels.

Risques bloquants : autorité sans session métier partagée, absence de transfert et
logout, rôle tenant Online non convenu, portée RP/origine, statut DB partagé inconnu.
Ne pas résoudre ces points par une exception staging, des JWT frontend, un cookie
d’enrôlement, des tables factices ou une copie globale Auth/Shop.

# Livraison intégrée Auth + SHOP-RC1

Cette archive conserve les protocoles Auth du commit
`2e12f5088888acfc93805c7a4f261afab068d5d4` et intègre le candidat RC1
`c1c03ac7e4172075786d350bd3b6cbe106f05e948120d4c71959d788e04be65b`.
Le manifeste décrit les octets intégrés ; le commit Auth seul ne les représente pas.

Python 3.12.13 et les dépendances Auth restent épinglés. Conserver :

```text
RAILPACK_INSTALL_CMD=python -m venv /app/.venv && /app/.venv/bin/python -m pip install -r requirements.txt
startCommand=/app/.venv/bin/python -m uvicorn deploy.pilot.runtime:app --host 0.0.0.0 --port $PORT
healthcheckPath=/health/db
healthcheckTimeout=120
```

Le runtime conserve la validation Core/Auth et la validation métier RC1 en
lecture seule. Aucun bootstrap, migration, seed ou réparation au démarrage.
Les réglages d’activation Auth et les secrets existants ne sont pas remplacés.
Aucune activation commerçant n’est autorisée par cette livraison.

Sur le pilote, `005_pilot_quick_login.sql` est déjà appliquée : ne pas la rejouer.
Après sauvegarde finale restaurée, confirmations terrain et drainage qualifié,
appliquer uniquement les étapes RC1 manquantes : `004_purchase_idempotency.sql`,
`app.db.finance_acceptances`, puis `app.db.payment_idempotence`, avec identités
de cible vérifiées et timeouts qualifiés. Ne pas inventer de fuseau ni de date.
Ne jamais utiliser l’initialisateur de base vide sur une base existante.

Ne pas revenir aux images antérieures qui perdraient Auth ou les protections RC1.
La reprise de cette même révision doit préserver configuration et reçus.
Une restauration des données requiert une procédure distincte tenant compte des
opérations postérieures à la sauvegarde. Ne jamais écraser automatiquement la base.

Les preuves de qualification et d’exploitation sont conservées hors de l’archive.
Les anciens guides Auth de préparation ne constituent pas un ordre de rollback.

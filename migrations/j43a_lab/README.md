# Migrations exclusivement locales J4.3A

Ne pas appliquer ces fichiers sur Railway, Shop, Auth ou une base existante.
Ils sont réservés au lanceur `python -B -m scripts.j43a.run` qui crée et vérifie ses propres conteneurs PostgreSQL 18.6.

001 fige le schéma ORM e34ea2f pour le laboratoire ; 002 prépare les reçus ; 003 applique les permissions/RLS ; 004 vérifie les références tenant pendant la co-localisation ; 005 retire UPDATE/DELETE inbox aux runtimes et réserve la purge au rôle de maintenance sous RLS et rétention >2160 heures. INSERT runtime exclut l'horodatage, généré par le serveur. Le journal transactionnel contrôle les SHA-256 ; 001–004 restent inchangées. Ce n'est pas une migration de séparation physique ni un chemin d'upgrade staging.

Voir `docs/online/j43a/ADR-001-PHYSICAL-SEPARATION.md` et `SECURITY_AND_RUNBOOK.md` pour les décisions bloquantes, la restauration et les critères J4.3B.

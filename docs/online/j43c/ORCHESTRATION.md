# Orchestration et machines à états

Implémentation isolée : `scripts/j43c/orchestrator.py`, `core.py`, `core.sql`, `client.sql`. Le simulateur Shop réutilise la saga mais écrit dans sa propre instance, sans import ni modification du code Shop existant.

```mermaid
sequenceDiagram
    participant O as Online / PostgreSQL Online
    participant C as Core / PostgreSQL Core
    participant P as PSP simulé / troisième PostgreSQL
    O->>O: TX commande + outbox ReserveStock
    O->>C: Commande signée (hors transaction SQL)
    C->>C: TX réservé + reçu + outbox résultat
    C-->>O: Résultat signé, au moins une fois
    O->>O: TX inbox + WAIT_PAYMENT
    P-->>O: Confirmation de paiement signée
    O->>O: TX inbox paiement + CAPTURED + outbox Confirm
    O->>C: ConfirmReservation
    C->>C: TX CONFIRMED + reçu + outbox
    C-->>O: Résultat confirmé
    O->>O: TX inbox + outbox Consume
    O->>C: ConsumeReservation
    C->>C: TX stock décrémenté + mouvement + reçu + outbox
    C-->>O: Résultat consommé
    O->>O: TX inbox + outbox RecordSale
    O->>C: RecordSale
    C->>C: TX vente RECORDED + reçu + outbox
    C-->>O: Résultat enregistré
    O->>O: TX inbox + COMPLETED
    Note over O,C: Timeout : conserver pending_key, résoudre par rejeu
    opt Annulation avant exécution matérielle
        O->>O: TX cancel_requested
        O->>C: ReleaseReservation ou CancelSale après résolution
        C->>C: TX libération/retour + reçu + outbox
        C-->>O: Résultat compensé
        O->>O: TX CANCELLED + refund_outbox si payé
        O->>P: Remboursement avec payment_id stable
        P->>P: TX reçu PSP synthétique
        P-->>O: ACK (peut être perdu)
        O->>O: TX REFUNDED + ACK refund_outbox
    end
```

La confirmation PSP est injectée par le test sous une identité synthétique. Le faux fournisseur de remboursement persiste ses reçus dans la troisième instance ; il ne s'agit pas d'un vrai PSP.

## Commande

```mermaid
stateDiagram-v2
    [*] --> WAIT_ReserveStock
    WAIT_ReserveStock --> WAIT_PAYMENT: résultat ACTIVE
    WAIT_PAYMENT --> WAIT_ConfirmReservation: paiement confirmé
    WAIT_ConfirmReservation --> WAIT_ConsumeReservation: résultat CONFIRMED
    WAIT_ConsumeReservation --> WAIT_RecordSale: résultat CONSUMED
    WAIT_RecordSale --> COMPLETED: vente RECORDED
    WAIT_ReserveStock --> OUTCOME_UNKNOWN: timeout
    WAIT_ConsumeReservation --> OUTCOME_UNKNOWN: timeout
    OUTCOME_UNKNOWN --> WAIT_PAYMENT: résultat réservé retrouvé
    OUTCOME_UNKNOWN --> WAIT_RecordSale: consommation retrouvée
    WAIT_PAYMENT --> WAIT_ReleaseReservation: annulation
    COMPLETED --> WAIT_CancelSale: annulation avec retour attesté
    WAIT_ReleaseReservation --> CANCELLED
    WAIT_CancelSale --> CANCELLED
    WAIT_ReserveStock --> FAILED: stock insuffisant
    WAIT_ConfirmReservation --> FAILED: expirée
    WAIT_ConsumeReservation --> FAILED: expirée
    WAIT_RecordSale --> MANUAL_REVIEW: erreur de protocole
```

`cancel_requested` est orthogonal à l'état. Il reste persisté pendant un paiement ou une commande Core en vol. Tout état d'attente de commande peut devenir OUTCOME_UNKNOWN. Les diagrammes illustrent les transitions principales ; le contrat exécutable est `_drive` et les tests de courses. Un ACK transport ne suffit pas à faire avancer la saga : elle attend le résultat Core, conservé dans son outbox.

## Réservation et paiement

```mermaid
stateDiagram-v2
    [*] --> ACTIVE: ReserveStock
    ACTIVE --> CONFIRMED: ConfirmReservation
    ACTIVE --> RELEASED: ReleaseReservation
    CONFIRMED --> RELEASED: ReleaseReservation
    ACTIVE --> EXPIRED: échéance Core
    CONFIRMED --> EXPIRED: échéance Core
    CONFIRMED --> CONSUMED: ConsumeReservation ou RecordSale
    CONSUMED --> CANCELLED: CancelSale + mouvement inverse
```

La vente suit `PENDING → RECORDED → CANCELLED` ou `PENDING → CANCELLED`. La consommation et l'enregistrement peuvent être atomiques dans Core. Aucun état terminal de réservation n'est ressuscité.

```mermaid
stateDiagram-v2
    [*] --> UNPAID
    UNPAID --> CAPTURED: confirmation signée / vente locale préallouée
    CAPTURED --> REFUND_PENDING: échec ou annulation du stock
    REFUND_PENDING --> REFUNDED: reçu du faux PSP
```

Une confirmation tardive sur une commande annulée déclenche un remboursement. Une répétition de confirmation ne ramène jamais REFUNDED à CAPTURED. Une panne de remboursement laisse REFUND_PENDING et sa sortie durable.

## Frontières de crash vérifiées

| Frontière | Reprise |
| --- | --- |
| Avant commit Online | Aucune commande ni outbox partielle ; même requête de création rejouable. |
| Avant émission de la commande | Outbox Online pending retrouvée après reconstruction de l'orchestrateur. |
| Avant outbox/commit Core | Effets annulés ; tests avec exception et processus arrêté par `os._exit`. |
| Après commit Core, avant réponse/ACK | Réservation persistée ; même reçu, même événement au rejeu ; aucun double effet. |
| Avant publication Core | Outbox Core non acquittée ; publication suivante. |
| Après réception Online, avant ACK publication | Inbox empêche le second effet ; ACK peut être répété. |
| Avant commit inbox | Inbox et transition annulées ensemble ; réception suivante applique l'effet. |
| Après remboursement simulé, avant ACK Online | Reçu PSP durable ; le même payment_id ne rembourse pas deux fois. |

Les exceptions de test interrompent la fonction au point nommé. Les cas `test_real_process_death_and_recovery` arrêtent réellement un processus Python avec une connexion active avant commit, ou après commit. Un test Uvicorn/requests sur loopback provoque aussi un vrai timeout de lecture HTTP après le commit Core puis retrouve le reçu au retry. La recette ne simule pas une panne disque/hôte ni une partition TCP avec proxy ; ces limites restent explicites.

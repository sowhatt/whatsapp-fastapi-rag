#!/usr/bin/env bash

set -u

# ============================================================
# CONFIGURATION
# ============================================================

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

BASE_URL="${BASE_URL:-https://web-production-cb4fc.up.railway.app}"
AUDIT_DIR="/tmp/whatzabi_latency_audit"
LOG_FILE="$AUDIT_DIR/railway.log"
HTTP_REPORT="$AUDIT_DIR/http_benchmark.txt"
FINAL_REPORT="$AUDIT_DIR/final_report.txt"

PROJECT_PYTHON=".venv/bin/python"

mkdir -p "$AUDIT_DIR"

# ============================================================
# VÉRIFICATION DE L’ENVIRONNEMENT
# ============================================================

printf '\n============================================================\n'
printf 'AUDIT DE LATENCE WHATZABI\n'
printf '============================================================\n'

if [ ! -x "$PROJECT_PYTHON" ]; then
    printf '❌ Python virtuel introuvable : %s\n' "$PROJECT_PYTHON"
    printf 'Exécute ce script depuis la racine du projet.\n'
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    printf '❌ Git introuvable malgré la restauration du PATH.\n'
    exit 1
fi

if ! command -v railway >/dev/null 2>&1; then
    printf '❌ Railway CLI introuvable.\n'
    printf 'Chemins testés : %s\n' "$PATH"
    exit 1
fi

printf '✅ Python  : %s\n' "$PROJECT_PYTHON"
printf '✅ Git     : %s\n' "$(command -v git)"
printf '✅ Railway : %s\n' "$(command -v railway)"
printf '✅ URL     : %s\n' "$BASE_URL"

# ============================================================
# ÉTAT GIT — L’AUDIT NE DOIT RIEN MODIFIER
# ============================================================

printf '\n=== ÉTAT GIT AVANT AUDIT ===\n'

git status --short --branch

# ============================================================
# BENCHMARK HTTP PUBLIC
# ============================================================

printf '\n=== BENCHMARK RAILWAY ===\n'

BASE_URL="$BASE_URL" \
"$PROJECT_PYTHON" - <<'PYHTTP' | tee "$HTTP_REPORT"
from __future__ import annotations

import os
import statistics
import time
import urllib.error
import urllib.request


base_url = os.environ["BASE_URL"].rstrip("/")

endpoints = (
    "/health",
    "/health/db",
)


def percentile(values, ratio):
    ordered = sorted(values)

    if not ordered:
        return 0.0

    index = int(
        round(
            (len(ordered) - 1) * ratio
        )
    )

    return ordered[index]


for endpoint in endpoints:
    durations = []
    statuses = []

    print()
    print(f"Endpoint : {endpoint}")

    for iteration in range(1, 11):
        url = base_url + endpoint
        started_at = time.perf_counter()

        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "whatzabi-performance-audit/1.0"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                response.read(512)
                status = response.status

        except urllib.error.HTTPError as exc:
            status = exc.code

        except Exception as exc:
            status = f"ERROR:{type(exc).__name__}"

        duration_ms = (
            time.perf_counter() - started_at
        ) * 1000

        durations.append(duration_ms)
        statuses.append(status)

        print(
            f"  appel {iteration:02d} : "
            f"{duration_ms:8.2f} ms "
            f"— HTTP {status}"
        )

        time.sleep(0.4)

    print(
        "  Résumé : "
        f"min={min(durations):.2f} ms | "
        f"moyenne={statistics.mean(durations):.2f} ms | "
        f"P50={statistics.median(durations):.2f} ms | "
        f"P95={percentile(durations, 0.95):.2f} ms | "
        f"max={max(durations):.2f} ms"
    )
PYHTTP

# ============================================================
# CAPTURE DES LOGS PENDANT LES TESTS WHATSAPP
# ============================================================

printf '\n============================================================\n'
printf 'TESTS WHATSAPP À EFFECTUER\n'
printf '============================================================\n'

printf '\nEnvoie maintenant ces 5 messages :\n\n'
printf '1. Premier commerçant — texte simple :\n'
printf '   "Quel est mon stock de riz ?"\n\n'

printf '2. Premier commerçant — message vocal :\n'
printf '   "Quel produit risque bientôt une rupture de stock ?"\n\n'

printf '3. Nouveau commerçant — texte simple :\n'
printf '   "Quels produits ai-je dans mon stock ?"\n\n'

printf '4. Nouveau commerçant — message vocal :\n'
printf '   "Comment évoluent mes ventes ?"\n\n'

printf '5. Répète immédiatement le message numéro 3.\n\n'

printf 'La capture des logs va commencer.\n'
printf 'Lorsque les 5 réponses WhatsApp sont arrivées,\n'
printf 'reviens ici et appuie sur ENTRÉE.\n\n'

: > "$LOG_FILE"

railway logs > "$LOG_FILE" 2>&1 &
RAILWAY_LOG_PID=$!

printf 'Capture Railway démarrée — PID %s\n' "$RAILWAY_LOG_PID"

read -r -p "Appuie sur ENTRÉE après les 5 tests WhatsApp... " _

if kill -0 "$RAILWAY_LOG_PID" 2>/dev/null; then
    kill "$RAILWAY_LOG_PID" 2>/dev/null || true
    wait "$RAILWAY_LOG_PID" 2>/dev/null || true
fi

printf '\n✅ Capture terminée : %s\n' "$LOG_FILE"

# ============================================================
# ANALYSE DES LOGS
# ============================================================

printf '\n=== ANALYSE DES LOGS ===\n'

LOG_FILE="$LOG_FILE" \
HTTP_REPORT="$HTTP_REPORT" \
FINAL_REPORT="$FINAL_REPORT" \
"$PROJECT_PYTHON" - <<'PYANALYSIS'
from __future__ import annotations

import json
import os
import re
from pathlib import Path


log_path = Path(os.environ["LOG_FILE"])
http_path = Path(os.environ["HTTP_REPORT"])
report_path = Path(os.environ["FINAL_REPORT"])

log_content = (
    log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if log_path.exists()
    else ""
)

http_content = (
    http_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if http_path.exists()
    else ""
)

interesting_markers = (
    "PERF_AUDIT",
    "INTENT AGENT TIMING",
    "timing",
    "latency",
    "elapsed",
    "duration",
    "retry",
    "timeout",
    "openai",
    "whisper",
    "transcri",
    "webhook",
    "error",
    "exception",
)

interesting_lines = []

for line in log_content.splitlines():
    lowered = line.lower()

    if any(
        marker.lower() in lowered
        for marker in interesting_markers
    ):
        interesting_lines.append(line)

perf_payloads = []

for line in log_content.splitlines():
    if "PERF_AUDIT" not in line:
        continue

    json_start = line.find("{")

    if json_start == -1:
        continue

    try:
        payload = json.loads(line[json_start:])
    except json.JSONDecodeError:
        continue

    perf_payloads.append(payload)

intent_timings = []

intent_pattern = re.compile(
    r"INTENT AGENT TIMING:\s*(\{.*\})"
)

for line in log_content.splitlines():
    match = intent_pattern.search(line)

    if match:
        intent_timings.append(match.group(1))

report_lines = [
    "=" * 70,
    "RAPPORT D’AUDIT DE LATENCE WHATZABI",
    "=" * 70,
    "",
    "1. BENCHMARK HTTP RAILWAY",
    "",
    http_content.strip() or "Aucune donnée HTTP.",
    "",
    "2. SYNTHÈSE DES LOGS",
    "",
    f"Lignes Railway capturées : "
    f"{len(log_content.splitlines())}",
    f"Lignes intéressantes : "
    f"{len(interesting_lines)}",
    f"Mesures PERF_AUDIT : "
    f"{len(perf_payloads)}",
    f"Mesures INTENT AGENT TIMING : "
    f"{len(intent_timings)}",
    "",
]

if perf_payloads:
    report_lines.extend(
        [
            "3. REQUÊTES MESURÉES",
            "",
        ]
    )

    for index, payload in enumerate(
        perf_payloads,
        start=1,
    ):
        report_lines.append(
            f"Requête {index} : "
            f"path={payload.get('path')} | "
            f"status={payload.get('status_code')} | "
            f"total={payload.get('total_ms')} ms | "
            f"request_id={payload.get('request_id')}"
        )

        for function in payload.get(
            "top_functions",
            [],
        )[:8]:
            report_lines.append(
                "  - "
                f"{function.get('function')} : "
                f"{function.get('total_ms')} ms "
                f"({function.get('calls')} appel(s))"
            )

        report_lines.append("")

if intent_timings:
    report_lines.extend(
        [
            "4. TEMPS DE L’AGENT D’INTENTION",
            "",
        ]
    )

    for index, timing in enumerate(
        intent_timings,
        start=1,
    ):
        report_lines.append(
            f"{index}. {timing}"
        )

    report_lines.append("")

report_lines.extend(
    [
        "5. LIGNES DE LOGS À ANALYSER",
        "",
    ]
)

if interesting_lines:
    report_lines.extend(
        interesting_lines[-200:]
    )
else:
    report_lines.append(
        "Aucune ligne de timing trouvée."
    )
    report_lines.append(
        "Le code devra être instrumenté "
        "dans une deuxième étape."
    )

report_lines.extend(
    [
        "",
        "6. INTERPRÉTATION RAPIDE",
        "",
        "- /health lent uniquement au premier appel : "
        "cold start Railway probable.",
        "- INTENT AGENT TIMING > 5 s : "
        "appel IA principal responsable.",
        "- retry_triggered=True : "
        "double appel ou timeout à corriger.",
        "- /health rapide mais réponse WhatsApp lente : "
        "problème applicatif, ASR, IA ou API Meta.",
        "- Nouveau commerçant seulement plus lent : "
        "résolution merchant/catalogue à auditer.",
        "- Texte rapide mais vocal lent : "
        "téléchargement média ou transcription.",
    ]
)

report = "\n".join(report_lines)

report_path.write_text(
    report,
    encoding="utf-8",
)

print(report)
print()
print(
    "Rapport enregistré :",
    report_path,
)
PYANALYSIS

# ============================================================
# ÉTAT FINAL
# ============================================================

printf '\n=== ÉTAT GIT APRÈS AUDIT ===\n'

git status --short --branch

printf '\n============================================================\n'
printf 'AUDIT TERMINÉ\n'
printf '============================================================\n'
printf 'Logs bruts : %s\n' "$LOG_FILE"
printf 'Rapport    : %s\n' "$FINAL_REPORT"
printf '\nAffichage du rapport :\n'
printf 'sed -n '\''1,260p'\'' %s\n' "$FINAL_REPORT"

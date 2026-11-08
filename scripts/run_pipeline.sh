#!/usr/bin/env bash
# Rejoue en local exactement les étapes de la CI (.github/workflows/ci.yml).
# Usage : ./scripts/run_pipeline.sh            (repart d'une base et d'un S3 vides)
#         INJECT_BUG=generation ./scripts/run_pipeline.sh
#         FAIL_INSERT_TIMES=2  ./scripts/run_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "0. Tests unitaires"
$PY -m pytest tests/unit -q

step "1. Démarrage S3 + PostgreSQL (état vierge)"
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --wait s3 postgres

step "2. Génération des CSV"
rm -rf data && $PY -m pipeline generate --out data

step "3. Dépôt dans le S3"
$PY -m pipeline upload --dir data

step "4. Schéma de la base"
$PY -m pipeline init-db

step "5. Traitement + insertion"
$PY -m pipeline process --source s3

step "6. Re-run (idempotence)"
$PY -m pipeline process --source s3 2>&1 | tee /dev/stderr | grep -q "'processed': 0, 'skipped': 3"

step "7. Tests d'intégration"
$PY -m pytest tests/integration -v -o log_cli=true -o log_cli_level=WARNING

printf '\n\033[1;32mPIPELINE OK\033[0m\n'

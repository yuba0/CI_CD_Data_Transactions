#!/usr/bin/env bash
# Déploie la production sur le cluster Kubernetes courant (kubectl context),
# puis lance un smoke test de bout en bout.
#
# Usage : IMAGE=ghcr.io/<user>/<repo>:<tag> POSTGRES_PASSWORD=... S3_SECRET_KEY=... \
#         ./scripts/deploy_k8s.sh [--smoke-test]
set -euo pipefail
cd "$(dirname "$0")/.."
: "${IMAGE:?IMAGE manquante}" "${POSTGRES_PASSWORD:?}" "${S3_SECRET_KEY:?}"
NS=pipeline
PY=${PY:-python3}
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "1. Namespace + secrets"
kubectl apply -f k8s/namespace.yaml
S3_JSON=$($PY -c 'import json,sys,os
c=json.load(open("infra/s3.json")); c["identities"][0]["credentials"][0]["secretKey"]=os.environ["S3_SECRET_KEY"]
print(json.dumps(c))')
kubectl -n $NS create secret generic pipeline-secrets \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=S3_SECRET_KEY="$S3_SECRET_KEY" \
  --from-literal=s3.json="$S3_JSON" \
  --dry-run=client -o yaml | kubectl apply -f -

step "2. Manifestes (image = $IMAGE)"
kubectl kustomize k8s | sed "s#image: transactions-pipeline:local#image: $IMAGE#" | kubectl apply -f -

step "3. Attente des services"
kubectl -n $NS rollout status statefulset/postgres --timeout=180s
kubectl -n $NS rollout status deployment/s3 --timeout=180s

[ "${1:-}" = "--smoke-test" ] || { echo "Déploiement OK"; exit 0; }

step "4. Smoke test : dépôt des fichiers dans le S3 du cluster"
kubectl -n $NS port-forward svc/s3 18333:8333 >/dev/null 2>&1 &
PF=$!; trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:18333/status && break; sleep 1; done
rm -rf /tmp/smoke-data
$PY -m pipeline generate --out /tmp/smoke-data
S3_ENDPOINT=http://127.0.0.1:18333 S3_SECRET_KEY="$S3_SECRET_KEY" $PY -m pipeline upload --dir /tmp/smoke-data

step "5. Exécution immédiate du CronJob"
JOB=smoke-$(date +%s)
kubectl -n $NS create job "$JOB" --from=cronjob/processor
kubectl -n $NS wait --for=condition=complete "job/$JOB" --timeout=300s \
  || { kubectl -n $NS logs "job/$JOB"; exit 1; }
kubectl -n $NS logs "job/$JOB" | tail -5

step "6. Vérification en base"
COUNT=$(kubectl -n $NS exec statefulset/postgres -- \
  psql -U pipeline -d transactions -tAc "SELECT COUNT(*) FROM transactions")
echo "transactions en base : $COUNT (attendu : 22)"
[ "$COUNT" = "22" ]

step "7. 2e exécution : rien ne doit être retraité"
kubectl -n $NS create job "$JOB-bis" --from=cronjob/processor
kubectl -n $NS wait --for=condition=complete "job/$JOB-bis" --timeout=300s
kubectl -n $NS logs "job/$JOB-bis" | grep "'processed': 0"
printf '\n\033[1;32mDÉPLOIEMENT KUBERNETES OK\033[0m\n'

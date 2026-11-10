# Pipeline data CI/CD : CSV → S3 → traitement → PostgreSQL → dashboard

```
generate.py ──► CSV ──► S3 local (SeaweedFS) ──► loader.py (retry) ──► processing.py (pur)
                                                                           │
                         Metabase ◄── PostgreSQL ◄── db.py (transaction + retry + registre)
```

## Démarrage rapide

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
./scripts/run_pipeline.sh            # rejoue toute la CI en local
docker compose --profile dashboard up -d   # dashboard Metabase : http://localhost:3001
```

## Arborescence

| Fichier | Rôle |
|---|---|
| `pipeline/generate.py` | 1.1 Génère 3 CSV (5, 6, 7 transactions), données **fixes** |
| `pipeline/generate_extra.py` | 3 Génère un relevé image (OCR) et un texte brut (SLM) |
| `pipeline/extractors.py` | 3 CSV / OCR / SLM → lignes au format CSV |
| `pipeline/processing.py` | 1.2 Fonctions **pures** : sommes, flag > 5000, validation |
| `pipeline/loader.py` | 1.2 / 2.3 Chargement (local ou S3) + 2.4 retry du téléchargement |
| `sql/schema.sql` | 1.3 Schéma relationnel |
| `pipeline/db.py` | 1.3 Insertion atomique + 1.7 retry |
| `pipeline/retry.py` | Décorateur de retry avec backoff exponentiel |
| `pipeline/faults.py` | Pannes simulées (`FAIL_INSERT_TIMES`, `FAIL_S3_GET_TIMES`) |
| `.github/workflows/ci.yml` | 1.4 / 2.2 Pipeline CI |
| `tests/expected.py` | Résultats attendus **calculés à la main** |
| `tests/unit/` | Tests des fonctions pures et du retry |
| `tests/integration/` | 1.5 Vérifie le contenu de la base, le retry et l'idempotence |
| `Dockerfile`, `docker-compose.prod.yml`, `k8s/`, `.github/workflows/cd.yml` | Niveau 3 : CD Docker, VM et Kubernetes |
| `tests/slm/` | Niveau 3 : test de l'extraction par le petit modèle |
| `infra/terraform/` | Niveau 3 : S3, RDS et EC2 sur AWS |

Format CSV : `datetime_transaction, iban_origine, pays_source, banque_source, iban_destinataire, pays_destinataire, montant`.
La colonne `montant` est ajoutée au format de l'énoncé, car les traitements en ont besoin.

---

## Niveau 1

### 1.1 Génération
`python -m pipeline generate --out data`. Le jeu de données est codé en dur dans `DATASET`. Il contient des cas limites
choisis exprès : `5000.00` (pas flaggé), `5000.01` et `4999.99`, et deux IBAN dans la même banque (Banque Alpha), pour que
la somme par banque diffère de la somme par IBAN.

### 1.2 Traitement
`processing.py` ne fait aucune I/O. `process(rows)` renvoie un `ProcessingResult` immuable.
Le chargement (`loader.py`) est séparé du traitement.

### 1.3 Base de données
- `processed_files` : registre des fichiers traités (clé + **sha256** du contenu)
- `transactions` : une ligne par transaction, avec `is_flagged`
- `sent_by_iban`, `sent_by_bank`, `received_by_iban` : agrégats par fichier
- vues `v_total_*` et `v_flagged_transactions` : totaux tous fichiers confondus, utilisés par le dashboard et les tests

### 1.4 Pipeline
Voir `ci.yml` : tests unitaires → démarrage S3 + DB → generate → upload → init-db → process → re-run (idempotence) → tests d'intégration.

### 1.5 Test d'intégration
`tests/integration/test_database_content.py` compare la base aux valeurs de `tests/expected.py` :
22 transactions (3 CSV et 1 image), total 76872.74, sommes par IBAN, par banque et par destinataire, et 8 transactions flaggées.

### 1.6 Scénario d'échec (captures d'écran)
Fais une capture d'écran de chaque étape et range-la dans `docs/screenshots/`.

1. **Pipeline verte** : push sur `main` → onglet *Actions* → capture du run vert.
2. **Bug dans la génération** : *Actions → CI → Run workflow* avec `inject_bug = generation`.
   Le générateur écrit `12O0.00` (lettre O). L'étape 5 échoue avec
   `montant invalide '12O0.00'`. Capture le run rouge et le log.
   (En local : `INJECT_BUG=generation ./scripts/run_pipeline.sh`.)
3. **Bug dans le traitement** : crée une branche `bug/flag`. Dans `processing.py`, remplace
   `return montant > threshold` par `return montant >= threshold`, puis push.
   Le job `unit-tests` devient rouge (`test_flag_threshold_is_strict[5000.00-False]`), et le job `pipeline`
   ne se lance pas. Capture l'échec.
4. Corrige le bug, push, et capture le retour au vert.

### 1.7 Bug d'insertion et retry
- `FAIL_INSERT_TIMES=N` fait planter l'insertion **après** l'écriture de lignes et **avant** le commit.
- `insert_results` est réessayée jusqu'à 5 fois, avec un backoff de 0.5s, 1s, 2s, etc. Chaque tentative ouvre une nouvelle connexion.
- Toute l'insertion d'un fichier se fait dans **une seule transaction SQL**. Une tentative ratée est annulée par un ROLLBACK, donc elle ne laisse aucune ligne partielle.
- Démo CI : *Run workflow* avec `fail_insert_times = 2` → les logs montrent 2 retries, puis les tests passent.
  Avec `fail_insert_times = 10`, l'échec est définitif et la base ne contient **0** ligne partielle.

### Ne jamais traiter deux fois un fichier
Trois garde-fous :
1. Avant le traitement, on cherche la clé **ou** le checksum dans `processed_files`. Une copie renommée est donc ignorée aussi.
2. L'enregistrement du fichier dans le registre et l'insertion des données sont dans la même transaction : un fichier est marqué « traité » si et seulement si ses données sont en base.
3. Les contraintes `PRIMARY KEY`/`UNIQUE` combinées à `ON CONFLICT DO NOTHING` protègent contre deux workers qui tourneraient en parallèle.

Ces garde-fous sont testés par `test_retry_idempotence.py`, et l'étape 6 de la CI vérifie que le re-run ne traite rien.

## Niveau 2
- 2.1 : S3 local **SeaweedFS** (`docker-compose.yml`, service `s3`, port 8333, identifiants dans `infra/s3.json`)
- 2.2 : la CI démarre le S3 en premier, puis `python -m pipeline upload` dépose les CSV dans `s3://transactions/incoming/`
- 2.3 : `process --source s3` lit depuis le S3 (`S3Source`)
- 2.4 : `_fetch_with_retry` réessaie le téléchargement en cas d'erreur réseau. Le test `test_s3_download_retry` le vérifie avec `FAIL_S3_GET_TIMES=2`.

## Niveau 3 : les 4 améliorations

Vue d'ensemble des jobs GitHub Actions :

```
CI : unit-tests ─┬─► pipeline (CSV + OCR, S3, Postgres, tests d'intégration)
                 └─► slm      (Ollama + qwen2.5:1.5b, extraction du texte brut)
     terraform   (fmt + validate de l'infra AWS)

CD (si la CI est verte sur main) : build-and-push (GHCR) ─┬─► deploy-kubernetes (kind + smoke test)
                                                          └─► deploy-vm (optionnel, DEPLOY_VM=true)
```

### 3.1 CD avec Docker vers Kubernetes et/ou une VM
- `Dockerfile` : l'image du traitement, qui contient Tesseract.
- **Kubernetes** (`k8s/`) : PostgreSQL en StatefulSet, SeaweedFS en Deployment (avec un PVC), et le traitement en
  **CronJob toutes les 5 minutes**. `concurrencyPolicy: Forbid` interdit deux traitements en parallèle, et
  `backoffLimit: 2` relance le Job s'il échoue.
  - `scripts/deploy_k8s.sh --smoke-test` déploie, dépose les fichiers dans le S3 du cluster, lance le CronJob tout de suite,
    vérifie qu'il y a 22 transactions en base, puis vérifie que la 2e exécution ne retraite rien.
  - Le job `deploy-kubernetes` de la CD crée un cluster **kind** dans le runner, y charge l'image publiée sur GHCR et lance ce script.
  - En local : `kind create cluster --name tp-cicd && kind load docker-image transactions-pipeline:local --name tp-cicd`,
    puis `IMAGE=transactions-pipeline:local POSTGRES_PASSWORD=x S3_SECRET_KEY=y PY=.venv/bin/python ./scripts/deploy_k8s.sh --smoke-test`.
- **VM** (`docker-compose.prod.yml`) : S3, PostgreSQL, le processor en boucle (`restart: unless-stopped`) et Metabase.
  Le job `deploy-vm` est désactivé par défaut. Pour l'activer, crée la variable de dépôt `DEPLOY_VM=true`, puis l'environment `production` avec les secrets
  `VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `POSTGRES_PASSWORD`, `S3_SECRET_KEY` et `GHCR_PAT`.

### 3.2 OCR : transactions contenues dans des images
- `generate_extra.py` dessine un relevé PNG (`releve_2026-01-04.png`) avec 4 transactions.
- `extractors.py` : Tesseract (`--psm 6`) lit l'image, puis `parse_ocr_text` (une fonction pure) découpe chaque ligne, retire les espaces
  que l'OCR insère dans les IBAN et vérifie le format de l'IBAN et du code pays. Une ligne mal lue donne une erreur au lieu d'une donnée fausse.
- Le relevé fait partie de la pipeline principale : la base attendue contient **22 transactions** (18 issues des CSV et 4 de l'image).

### 3.3 Petit modèle de langage : transactions contenues dans du texte brut
- `message_2026-01-05.txt` décrit 2 virements en français libre (« le 2026-01-05 vers 16h20, le client du compte … a envoyé 6400.00 EUR … »).
- `ask_slm` interroge **Ollama** avec le modèle `qwen2.5:1.5b` :
  - le schéma JSON imposé par `format` oblige une sortie structurée ;
  - `temperature=0` et `seed=42` rendent la réponse reproductible ;
  - l'appel a un retry si Ollama ne répond pas.
- **Garde-fou contre les hallucinations** : chaque IBAN et chaque montant renvoyé doit apparaître mot pour mot dans le texte source.
  Sinon le fichier est rejeté. C'est testé dans `tests/unit/test_extractors.py`.
- En local : `docker compose --profile slm up -d --wait ollama && docker compose exec ollama ollama pull qwen2.5:1.5b`,
  puis `python -m pipeline generate --texts` et `pytest tests/slm`.

### 3.4 Terraform : production dans le cloud (AWS)
`infra/terraform/` décrit :
- un **bucket S3**, chiffré et sans accès public ;
- une base **RDS PostgreSQL 16** accessible seulement depuis la VM ;
- une **VM EC2** qui installe Docker au démarrage (cloud-init) et lance le conteneur de traitement en boucle. Elle lit le S3
  avec un **rôle IAM**, sans clé d'accès stockée.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # renseigner l'image (le paquet GHCR doit être public)
terraform init && terraform plan && terraform apply
aws s3 cp ../../data/ s3://$(terraform output -raw bucket)/incoming/ --recursive
terraform destroy   # à la fin du TP, pour ne pas payer
```
La CI vérifie `terraform fmt` et `terraform validate`, ce qui ne demande aucun compte AWS.

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
| `Dockerfile`, `docker-compose.prod.yml`, `.github/workflows/cd.yml` | Niveau 3 : CD |

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
18 transactions, total 60951.24, sommes par IBAN, par banque et par destinataire, et 6 transactions flaggées.

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

## Niveau 3 : CD sur une VM avec Docker
- `Dockerfile` : image du traitement. Par défaut, elle tourne en boucle (`--loop`) et vérifie le S3 toutes les `PROCESS_INTERVAL` secondes.
  `restart: unless-stopped` la relance si elle plante.
- `docker-compose.prod.yml` : S3, PostgreSQL (volumes persistants), le processor et Metabase.
- `cd.yml` : se déclenche quand la CI est verte sur `main`. Il construit l'image, la pousse sur GHCR, la copie sur la VM via SSH, lance `docker compose up -d` et termine par un smoke test.

Prérequis sur la VM : Docker et l'accès SSH par clé. Dans GitHub, crée un environment `production` avec les secrets
`VM_HOST`, `VM_USER`, `VM_SSH_KEY`, `POSTGRES_PASSWORD`, `S3_SECRET_KEY` et `GHCR_PAT`.
